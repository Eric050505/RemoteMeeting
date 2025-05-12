
from config import *

from io import BytesIO
import time
import json
import asyncio
import datetime
import threading
import base64
import aioconsole
import noisereduce as nr
import pyaudio
import cv2
import pyautogui
import numpy as np
# from pydub import AudioSegment
from PIL import Image, ImageGrab, ImageTk
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaRelay

import traceback
import socketserver
import socket
import websockets
from PyQt5 import QtWidgets, QtCore, QtGui
from qasync import QEventLoop, asyncSlot


# audio setting
FORMAT = pyaudio.paInt16
audio = pyaudio.PyAudio()
streamin = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
streamout = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)

# print warning if no available camera
cap = cv2.VideoCapture(0)
if cap.isOpened():
    can_capture_camera = True
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, camera_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, camera_height)
else:
    can_capture_camera = False

my_screen_size = pyautogui.size()


def resize_image_to_fit_screen(image, my_screen_size):
    screen_width, screen_height = my_screen_size

    original_width, original_height = image.size

    aspect_ratio = original_width / original_height

    if screen_width / screen_height > aspect_ratio:
        # resize according to height
        new_height = screen_height
        new_width = int(new_height * aspect_ratio)
    else:
        # resize according to width
        new_width = screen_width
        new_height = int(new_width / aspect_ratio)

    # resize the image
    resized_image = image.resize((new_width, new_height), Image.LANCZOS)

    return resized_image


def overlay_camera_images(screen_image, camera_images): #把投屏信息和摄像头信息合在一张图片上
    """
    screen_image: PIL.Image
    camera_images: list[PIL.Image]
    """
    if screen_image is None and camera_images is None:
        # print('[Warn]: cannot display when screen and camera are both None')
        return None

    if screen_image is not None:
        screen_image = resize_image_to_fit_screen(screen_image, my_screen_size)

    if camera_images is not None:
        # make sure same camera images
        if not all(img.size == camera_images[0].size for img in camera_images):
            raise ValueError("All camera images must have the same size")

        screen_width, screen_height = my_screen_size if screen_image is None else screen_image.size
        camera_width, camera_height = camera_images[0].size

        # calculate num_cameras_per_row
        num_cameras_per_row = screen_width // camera_width

        # adjust camera_imgs
        # if len(camera_images) > num_cameras_per_row:
        #     adjusted_camera_width = screen_width // len(camera_images)
        #     adjusted_camera_height = (adjusted_camera_width * camera_height) // camera_width
        #     camera_images = [img.resize((adjusted_camera_width, adjusted_camera_height), Image.LANCZOS) for img in
        #                      camera_images]
        #     camera_width, camera_height = adjusted_camera_width, adjusted_camera_height
        #     num_cameras_per_row = len(camera_images)

        # if no screen_img, create a container
        if screen_image is None:
            display_image = Image.fromarray(np.zeros((camera_width, my_screen_size[1], 3), dtype=np.uint8))
        else:
            display_image = screen_image
        # cover screen_img using camera_images
        for i, camera_image in enumerate(camera_images):
            camera_image = camera_image.resize(
                (int(camera_width * 0.6), int(camera_height * 0.6)),
                Image.LANCZOS
            )
            row = i // num_cameras_per_row
            col = i % num_cameras_per_row
            x = int(col * camera_width * 0.8 + camera_width* 0.7)
            y = int(row * camera_height * 0.8)
            display_image.paste(camera_image, (x, y))

        return display_image
    else:
        return screen_image


def capture_screen():
    # capture screen with the resolution of display
    # img = pyautogui.screenshot()
    img = ImageGrab.grab()
    return img


def capture_camera():
    # capture frame of camera
    ret, frame = cap.read()
    if not ret:
        raise Exception('Fail to capture frame from camera')
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(frame_rgb)

    return pil_image

def capture_voice():
    return streamin.read(CHUNK) #从麦克风中读取音频数据

def compress_image(image, format='JPEG', quality=85):
    """
    compress image and output Bytes

    :param image: PIL.Image, input image
    :param format: str, output format ('JPEG', 'PNG', 'WEBP', ...)
    :param quality: int, compress quality (0-100), 85 default
    :return: bytes, compressed image data
    """
    img_byte_arr = BytesIO()
    image.save(img_byte_arr, format=format, quality=quality)
    img_byte_arr = img_byte_arr.getvalue()
    return img_byte_arr


def decompress_image(image_bytes):
    """
    decompress bytes to PIL.Image
    :param image_bytes: bytes, compressed data
    :return: PIL.Image
    """
    img_byte_arr = BytesIO(image_bytes)
    image = Image.open(img_byte_arr)


    return image

# 用来记录已经使用的端口
class PortPool:
    def __init__(self, start_port, end_port):
        self.pool = list(range(start_port, end_port + 1))
        np.random.shuffle(self.pool)  # 随机打乱端口池
        self.used_ports = set()  # 使用集合存储已使用的端口

    def get_ports(self, num_ports):
        """
        分配指定数量的可用端口。

        :param num_ports: 需要分配的端口数量
        :return: 分配的端口列表，如果不足则返回None
        """
        allocated_ports = []

        for port in self.pool:
            if port not in self.used_ports and self.is_port_free(port):
                allocated_ports.append(port)
                self.used_ports.add(port)
                if len(allocated_ports) == num_ports:
                    return allocated_ports

        # 如果可用端口不足，则释放已分配的端口并返回None
        for port in allocated_ports:
            self.used_ports.remove(port)
        return None

    def release_ports(self, ports):
        """
        释放一组端口。

        :param ports: 要释放的端口列表
        """
        for port in ports:
            if port in self.used_ports:
                self.used_ports.remove(port)

    def is_port_free(self, port):
        """
        检查端口是否可用。

        :param port: 要检查的端口号
        :return: 如果端口可用返回True，否则返回False
        """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('localhost', port))
            s.close()
            return True
        except socket.error:
            return False