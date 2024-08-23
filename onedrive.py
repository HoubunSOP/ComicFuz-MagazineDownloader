import json
import os
import time
import webbrowser
from urllib.parse import urlparse, parse_qs

import requests
from tqdm import tqdm


class OneDrive:
    def __init__(self):
        self.client_id = ''
        self.client_secret = ''
        self.redirect_uri = 'http://localhost:8400'
        self.oauth2_uri = 'https://login.microsoftonline.com/common/oauth2/token'
        self.resource_uri = 'https://graph.microsoft.com'
        self.onedrive_uri = f'{self.resource_uri}/v1.0/me/drive'
        self.scope = 'offline_access onedrive.readwrite'
        self.header = {'Content-Type': 'application/x-www-form-urlencoded'}

        self.token = self.read_token()['access_token']
        self.header['Authorization'] = f'Bearer {self.token}'

    def get_code(self):
        auth_url = (
            'https://login.microsoftonline.com/common/oauth2/authorize?'
            f'response_type=code&client_id={self.client_id}&redirect_uri={self.redirect_uri}'
        )
        webbrowser.open(auth_url, new=0, autoraise=True)

    def get_token(self, auth_url):
        code = parse_qs(urlparse(auth_url).query).get('code', [None])[0]
        if not code:
            raise ValueError("Invalid authorization URL provided.")

        data = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'client_secret': self.client_secret,
            'code': code,
            'grant_type': 'authorization_code',
            'resource': self.resource_uri
        }
        resp = requests.post(self.oauth2_uri, headers=self.header, data=data).json()
        return self.save_token(resp)

    def refresh_token(self):
        token = self.read_token(only_read=True)
        data = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'client_secret': self.client_secret,
            'refresh_token': token['refresh_token'],
            'grant_type': 'refresh_token',
            'resource': 'https://graph.microsoft.com'
        }
        resp = requests.post(self.oauth2_uri, headers=self.header, data=data).json()
        return self.save_token(resp)

    @staticmethod
    def save_token(resp):
        if 'error' in resp:
            raise Exception(f"Error saving token: {resp['error_description']}")

        token = {
            'access_token': resp['access_token'],
            'refresh_token': resp['refresh_token'],
            'expires_on': int(resp['expires_on'])
        }
        with open('token.json', 'w') as f:
            json.dump(token, f)
        return token

    def read_token(self, only_read=False):
        if os.path.exists('token.json'):
            with open('token.json', 'r') as f:
                token = json.load(f)
        else:
            self.get_code()
            token = self.get_token(input('请输入Url：'))

        if only_read:
            return token

        if token['expires_on'] <= int(time.time()):
            token = self.refresh_token()

        return token

    def get_path(self, path, op):
        path = path.strip('/')
        op = op.strip('/')
        return f'{self.onedrive_uri}/root:/{path}:/{op}'

    def create_folder(self, path):
        path_parts = list(filter(None, path.split('/')))
        parent_path = '/'.join(path_parts[:-1])
        folder_name = path_parts[-1]

        data = json.dumps({"name": folder_name, "folder": {}})
        response = requests.post(self.get_path(parent_path, 'children'), headers=self.header, data=data)
        return response.status_code

    def upload_url(self, path, conflict="fail"):
        response = requests.post(self.get_path(path, 'createUploadSession'), headers=self.header)
        return response.json().get('uploadUrl', '')

    def upload_file(self, path, data):
        if len(data) > 4 * 1024 * 1024:  # 4MB threshold
            return self.upload_big_file(path, data)

        response = requests.put(self.get_path(path, 'content'), headers=self.header, data=data)
        return "上传成功" if response.status_code in [200, 201] else "上传失败"

    def upload_big_file(self, path, data):
        upload_url = self.upload_url(path)
        if not upload_url:
            return "上传取消"

        size = len(data)
        chunk_size = 3276800  # 3.125MB
        file_name = path.split('/')[-1]
        pbar = tqdm(total=size, leave=False, unit='B', unit_scale=True, desc=file_name)

        for i in range(0, size, chunk_size):
            chunk_data = data[i:i + chunk_size]
            pbar.update(len(chunk_data))
            response = requests.put(upload_url, headers={
                'Content-Length': str(len(chunk_data)),
                'Content-Range': f'bytes {i}-{i + len(chunk_data) - 1}/{size}'
            }, data=chunk_data)
            if response.status_code not in [200, 201, 202]:
                print("上传出错")
                break
        pbar.close()
        return "上传成功" if response.status_code in [200, 201] else "上传失败"


one = OneDrive()
