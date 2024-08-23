# 通过QQBot框架进行群文件上传
# QQBot暂时只支持正向Http（因为完全可以不需要接入大框架，直接使用cq这种无头端即可）
import requests
import json


def send_message(group_id, message):
    url = "http://127.0.0.1:8082/send_group_msg"
    headers = {"Content-Type": "application/json"}
    data = {"group_id": group_id, "message": message}
    response = requests.post(url, headers=headers, data=json.dumps(data))
    return response.json().get('status') == 'ok'


def upload_file(group_id, file_path, file_name):
    url = "http://127.0.0.1:8082/upload_group_file"
    headers = {"Content-Type": "application/json"}
    data = {"group_id": group_id, 'file': file_path, "name": file_name}
    response = requests.post(url, headers=headers, data=json.dumps(data))
    return response.json().get('status') == 'ok'


def process_group_ids(group_ids, file_path, file_name):
    for group_id in group_ids:
        # 发送上传文件通知
        send_message(group_id, "即将上传文件")
        # 上传文件
        if not upload_file(group_id, file_path, file_name):
            send_message(group_id, "上传失败，需要联系雪绫钩纱")
            exit(0)
        # 发送上传完成通知
        send_message(group_id,
                     f"{file_name}上传完成，因为某种原因还请查看群文件是否上传成功，如果没有的话还请联系雪绫钩纱人工上传qwq")


# 示例调用
group_ids = [104303]  # 可以是单个ID或ID列表
file_path = 'D:\\misaka10843\\Downloads\\[Max]2024年9月号.zip'
file_name = "[Max]2024年9月号.zip"

process_group_ids(group_ids, file_path, file_name)
