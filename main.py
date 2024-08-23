import json
import os
import random
import re
import shutil
import time
from queue import Queue
from threading import Thread
from zipfile import ZipFile

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from google.protobuf import json_format
from rich import print
from rich.console import Console
from rich.progress import track

import fuz_pb2

console = Console()


class ComicFuzExtractor:
    COOKIE = "is_logged_in=true; fuz_session_key="
    USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, Gecko) Chrome/126.0.0.0 "
                  "Safari/537.36 Edg/126.0.0.0")

    API_HOST = "https://api.comic-fuz.com"
    IMG_HOST = "https://img.comic-fuz.com"
    TABLE = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
    T_MAP = {s: i for i, s in enumerate(TABLE)}

    def __init__(self, output_dir: str, user_email: str, password: str, token_file: str, proxy: str, magazine: str,
                 compress: bool = False, check_update: bool = False):
        self.output_dir = output_dir
        self.user_email = user_email
        self.password = password
        self.token_file = token_file
        self.proxy = {'http': f'http://{proxy}', 'https': f'http://{proxy}'} if proxy else {}
        self.magazine = magazine
        self.compress = compress
        self.check_update = check_update

        os.makedirs(self.output_dir, exist_ok=True)
        self.token = self.get_session()

    def run(self):
        if self.check_update:
            self.check_and_update()
        elif self.magazine:
            self.download_magazines()
        else:
            print("[bold red]您并没有填写杂志ID并没有开启更新模式")
            exit(1)

    def get_session(self) -> str:
        if self.token_file and os.path.exists(self.token_file):
            with open(self.token_file) as f:
                token = f.read().strip()
            if self.check_sign(token):
                return token
        return self.sign()

    def sign(self) -> str:
        body = fuz_pb2.SignInRequest()
        body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER
        body.email = self.user_email
        body.password = self.password
        url = self.API_HOST + "/v1/sign_in"
        response = requests.post(url, data=body.SerializeToString(), proxies=self.proxy)
        res = fuz_pb2.SignInResponse()
        res.ParseFromString(response.content)
        if not res.success:
            print("[bold red]登录失败,请检查您的账号密码是否准确无误")
            exit(1)
        token = None
        for header in response.headers:
            m = re.match(r'fuz_session_key=(\w+)(;.*)?', response.headers[header])
            if m:
                token = m.group(1)
                break
        if token and self.token_file:
            with open(self.token_file, "w") as f:
                f.write(token)
            print(f"[bold green]您的token已经存放到{self.token_file}中,请妥善保管")
        return token

    def check_sign(self, token: str) -> bool:
        url = self.API_HOST + "/v1/web_mypage"
        headers = {
            "user-agent": self.USER_AGENT,
            "cookie": self.COOKIE + token
        }
        response = requests.post(url, headers=headers, proxies=self.proxy)
        res = fuz_pb2.WebMypageResponse()
        res.ParseFromString(response.content)
        if res.mailAddress:
            print(f"[#FFB6C1]Login as: {res.mailAddress}")
            return True
        return False

    def get_store_index(self):
        body = fuz_pb2.BookStorePageRequest()
        body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER
        res = self.get_index("/v1/store_3", body.SerializeToString())
        index = fuz_pb2.BookStorePage()
        index.ParseFromString(res)

        updates = []
        search_string = "まんがタイムきらら"
        for detail in index.info.nested_message3[0].details:
            if search_string not in str(detail.magazineName):
                continue
            updates.append({
                'id': detail.id,
                'date': str(detail.updateDate1[:-3]),
                'name': str(detail.magazineName)
            })
        return updates

    def check_and_update(self):
        updates = self.get_store_index()
        stored_data = self.load_stored_data()

        if not stored_data:
            self.save_data(updates)
            print("[bold green]首次获取数据，已存储。")
            return

        latest_stored_id = max([int(data['id']) for data in stored_data])

        for update in updates:
            if int(update['id']) > latest_stored_id:
                que = Queue(4)
                Thread(target=self.worker, args=(que,), daemon=True).start()
                downloaded_info = self.down_magazine(int(update['id']), que)
                if self.compress:
                    print(downloaded_info)
                    self.compression(downloaded_info[0], downloaded_info[1], downloaded_info[2])
                self.save_data(updates)
                break

    def load_stored_data(self):
        if os.path.exists('store_data.json'):
            with open('store_data.json', 'r', encoding='utf-8') as f:
                return json.load(f)
        return []

    def save_data(self, data):
        with open('store_data.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def download_magazines(self):
        que = Queue(4)
        Thread(target=self.worker, args=(que,), daemon=True).start()
        if ',' in self.magazine:
            for item in self.magazine.split(','):
                downloaded_info = self.down_magazine(int(item), que)
                if self.compress:
                    print(downloaded_info)
                    self.compression(downloaded_info[0], downloaded_info[1], downloaded_info[2])
                random_time = random.randint(10, 20)
                print(f"[bold blue]正在等待{random_time}s之后继续下载")
                time.sleep(random_time)
        else:
            downloaded_info = self.down_magazine(int(self.magazine), que)
            if self.compress:
                print(downloaded_info)
                self.compression(downloaded_info[0], downloaded_info[1], downloaded_info[2])
        print(f"[bold green]所有任务已全部运行完成!")

    def get_index(self, path: str, body: str) -> bytes:
        url = self.API_HOST + path
        headers = {"user-agent": self.USER_AGENT}
        if self.token:
            headers["cookie"] = self.COOKIE + self.token

        response = requests.post(url, data=body, headers=headers, proxies=self.proxy)

        if response.status_code != 200:
            raise Exception("获取相关信息出错！请检查ID参数是否正确！或者稍后重试")

        return response.content

    def get_magazine_index(self, magazine_id: int) -> fuz_pb2.MagazineViewer2Response:
        body = fuz_pb2.MagazineViewer2Request()
        body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER
        body.magazineIssueId = magazine_id
        body.viewerMode.imageQuality = fuz_pb2.ViewerMode.ImageQuality.HIGH

        res = self.get_index("/v1/magazine_viewer_2", body.SerializeToString())
        index = fuz_pb2.MagazineViewer2Response()
        index.ParseFromString(res)
        return index

    def down_magazine(self, magazine_id, que):
        magazine = self.get_magazine_index(magazine_id)
        magazine_name = self.get_magazine_name(magazine.magazineIssue.magazineName)
        folder_name = f"{magazine_name}/[{magazine_name}]{self.has_numbers(str(magazine.magazineIssue.magazineIssueName))}"
        self.down_pages(
            f"{self.output_dir}/{folder_name}/",
            magazine, que,
            f"[{magazine_name}]{magazine.magazineIssue.magazineIssueName}[/]")
        print(
            f"[bold green]{self.has_numbers(str(magazine.magazineIssue.magazineIssueName))}下载完成！如果下载时遇见报错,请重新运行一下命令即可")
        return folder_name, magazine_name, self.has_numbers(str(magazine.magazineIssue.magazineIssueName))

    def down_pages(self, save_dir: str, data, que: Queue, book_name: str):
        os.makedirs(save_dir, exist_ok=True)
        with open(save_dir + "index.protobuf", "wb") as f:
            f.write(data.SerializeToString())
        with open(save_dir + "index.json", "w", encoding='utf-8') as f:
            json.dump(json_format.MessageToDict(data),
                      f, ensure_ascii=False, indent=4)

        for page in track(data.pages, description=f"[bold yellow]正在下载:{book_name}[/]"):
            t = Thread(target=self.download, name=page.image.imageUrl,
                       args=(save_dir, page.image))
            t.start()
            que.put(t)
        que.join()

    def download(self, save_dir: str, image: fuz_pb2.ViewerPage.Image, overwrite=False):
        if not image.imageUrl:
            print(f"[blue]无法获取图片链接,返回内容如下: {image}")
            return
        name = re.match(r'.*/([0-9a-zA-Z_-]+)\.(\w+)\.enc\?.*', image.imageUrl)
        if not name or not name.group(1):
            print(f"[blue]无法检测文件名,返回内容如下: {image}")
            return
        name_num = "%03d" % self.b64_to_10(name.group(1))
        name = f"{save_dir}{name_num}.{name.group(2)}"
        if not overwrite and os.path.exists(name):
            print(f"图片已有,将跳过此图片,返回内容如下: {name}")
            return
        data = requests.get(self.IMG_HOST + image.imageUrl, proxies=self.proxy).content
        key = bytes.fromhex(image.encryptionKey)
        iv = bytes.fromhex(image.iv)
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        out = decryptor.update(data) + decryptor.finalize()
        with open(name, "wb") as f:
            f.write(out)

    def compression(self, download_dir: str, magazine_name: str, magazine_issue_name: str):
        print("[bold yellow]正在进行压缩中...")
        with console.status(f"[bold yellow]正在将{download_dir}压缩成zip中"):
            file_paths = []
            try:
                for root, _, files in os.walk(f'{self.output_dir}/{download_dir}'):
                    for file in files:
                        file_path = os.path.join(root, file)
                        file_paths.append(file_path)
                with ZipFile(f'{self.output_dir}/{magazine_name}/[{magazine_name}]{magazine_issue_name}.zip', 'w') as z:
                    for file_path in file_paths:
                        relative_path = os.path.relpath(file_path, os.path.join(self.output_dir, download_dir))
                        z.write(file_path, arcname=relative_path)
            finally:
                shutil.rmtree(f'{self.output_dir}/{download_dir}')
        print(
            f"[bold green]已经将图片打包压缩到{self.output_dir}/{magazine_name}/[{magazine_name}]{magazine_issue_name}.zip")

    def worker(self, que):
        while True:
            item = que.get()
            item.join()
            que.task_done()

    @staticmethod
    def b64_to_10(s: str) -> int:
        i = 0
        for c in s:
            i = i * 64 + ComicFuzExtractor.T_MAP[c]
        return i

    @staticmethod
    def get_magazine_name(magazine_name):
        names = {
            'まんがタイムきらら': "Kirara",
            'まんがタイムきららMAX': "Max",
            'まんがタイムきららキャラット': "Carat",
            'まんがタイムきららフォワード': "Forward"
        }
        return names.get(magazine_name, magazine_name)

    @staticmethod
    def has_numbers(chat):
        return "".join(str(int(i)) if i.isdigit() else i for i in chat)


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv

    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("magazine", type=int, help="Magazine number to extract")
    args = parser.parse_args()

    # 从环境变量中获取参数
    output_dir = os.getenv("OUTPUT_DIR")
    user_email = os.getenv("USER_EMAIL")
    password = os.getenv("PASSWORD")
    token_file = os.getenv("TOKEN_FILE")
    proxy = os.getenv("PROXY")
    compress = os.getenv("COMPRESS", "False").lower() in ("true", "1", "t")
    check_update = os.getenv("CHECKUpdated", "False").lower() in ("true", "1", "t")

    # 创建实例并运行
    extractor = ComicFuzExtractor(output_dir, user_email, password, token_file, proxy, str(args.magazine), compress,
                                  check_update)
    extractor.run()
