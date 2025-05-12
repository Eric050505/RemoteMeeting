import asyncio
import os
import traceback
from asyncio import CancelledError
from cryptography.fernet import Fernet

from util import *


class ConferenceClient(QtCore.QObject):
    # 定义信号以便在GUI中显示信息
    log_signal = QtCore.pyqtSignal(str)
    video_frame_signal = QtCore.pyqtSignal(np.ndarray)

    def __init__(self):
        super().__init__()
        self.server_addr = SERVER_IP  # Server address
        self.on_meeting = False  # Status
        self.support_data_types = ['text', 'audio', 'video', 'screen']  # Supported data types
        self.share_data = {  # 存储每一种数据类型的writer
            'video': None,
            'screen': None,
            'audio': None
        }
        self.conference_id = None
        self.is_creator = False
        self.reader = None  # Main command reader
        self.writer = None  # Main command writer

        self.data_connections = {}  # data_type: (reader, writer)
        self.DATA_SERVER_PORT_MAPPING = {}
        self.audio_buffer = None

        # 初始化任务列表
        self.tasks = []

        # 使用锁来防止同时启动多个任务
        self.lock = asyncio.Lock()

        key_path = './secret.key'
        if not os.path.exists(key_path):
            self.log_signal.emit(f"[Error]: E")
            raise FileNotFoundError("Encryption key file not found.")

        with open(key_path, 'rb') as key_file:
            self.key = key_file.read()
        self.cipher = Fernet(self.key)

    async def open_connection(self):
        """Open the main connection for commands."""
        while True:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.server_addr, MAIN_SERVER_PORT)
                self.log_signal.emit("Main connection established.")
                break
            except Exception as e:
                self.log_signal.emit(f"[Error] Failed to establish main connection: {e} Try connection again...")

    async def open_data_connection(self, data_type):
        """
        Open a separate connection for a specific data type.
        """
        try:
            port = self.DATA_SERVER_PORT_MAPPING.get(data_type, MAIN_SERVER_PORT)
            reader, writer = await asyncio.open_connection(self.server_addr, port)
            self.data_connections[data_type] = (reader, writer)
            self.log_signal.emit(f"Data connection for '{data_type}' established on port {port}.")
        except Exception as e:
            self.log_signal.emit(f"[Error] Failed to open connection for {data_type}: {e}")

    async def close_data_connections(self):
        """Close all data type connections."""
        for data_type, (reader, writer) in self.data_connections.items():
            try:
                writer.close()
                await writer.wait_closed()
                self.log_signal.emit(f"Data connection for '{data_type}' closed.")
            except Exception as e:
                self.log_signal.emit(f"[Error] Failed to close connection for {data_type}: {e}")
        self.data_connections.clear()

    async def close_conference(self):
        """
        Close all connections to servers or other clients and cancel the running tasks.
        Pay attention to exception handling to ensure graceful shutdown.
        """
        async with self.lock:
            try:
                if self.writer:
                    self.writer.close()
                    await self.writer.wait_closed()
                    self.writer = None
                if self.reader:
                    self.reader = None

                await self.close_data_connections()

                self.on_meeting = False
                self.conference_id = None
                self.is_creator = False
                self.log_signal.emit("All conference connections closed and cleaned up.")
            except Exception as e:
                self.log_signal.emit(f"[Error] Failed to close conference properly: {e}")

    async def send_request(self, message, writer=None):
        """
        Send a request message to the server.
        Ensures that the request is properly formatted and transmitted over the connection.
        """
        try:
            message_json = json.dumps(message)
            target_writer = writer if writer else self.writer
            if not target_writer:
                self.log_signal.emit("[Error] No connection established.")
                return
            target_writer.write(message_json.encode() + b'\n')  # Adding newline as delimiter
            await target_writer.drain()
        except Exception as e:
            self.log_signal.emit(f"[Error] Failed to send request: {e}")

    async def read_response(self, reader=None):
        """
        Read and decode the response from the server.
        """
        try:
            target_reader = reader if reader else self.reader
            if not target_reader:
                self.log_signal.emit("[Error]: No connection established.")
                return None
            data = b''
            while True:
                try:
                    chunk = await target_reader.readuntil(separator=b'\n')
                    data += chunk.strip()
                    break
                except asyncio.exceptions.LimitOverrunError as e:
                    chunk = await target_reader.read(e.consumed)
                    data += chunk
                except asyncio.exceptions.IncompleteReadError:
                    print('connect Interupted')
                    await self.quit_conference()
                    return
            if data:
                return json.loads(data.decode())
            return None
        except RuntimeError as re:
            print(re)
            print(asyncio.all_tasks())
            return
        except Exception as e:
            print(f"[Error] Failed to read response: {e}")
            traceback.print_exc()
            return None

    async def create_conference(self):
        """
        Create a conference: send create-conference request to server and obtain necessary data.
        """
        async with self.lock:
            message = {'action': 'create'}
            await self.send_request(message)

            response = await self.read_response()
            if response and response.get('status') == 'success':
                self.conference_id = response.get('conference_id')
                self.DATA_SERVER_PORT_MAPPING = response.get('ports')
                self.on_meeting = True
                self.is_creator = True
                self.log_signal.emit(f"Conference {self.conference_id} created successfully.")
                await self.start_conference()
            else:
                self.log_signal.emit("[Error]: Failed to create conference.")

    async def join_conference(self, conference_id):
        """
        Join a conference: send join-conference request with given conference_id.
        """
        async with self.lock:
            message = {'action': 'join', 'conference_id': conference_id}
            await self.send_request(message)

            response = await self.read_response()
            if response:
                self.log_signal.emit(str(response))
            if response and response.get('status') == 'success':
                self.conference_id = conference_id
                self.DATA_SERVER_PORT_MAPPING = response.get('ports')
                self.on_meeting = True
                self.log_signal.emit(f"Successfully joined conference {self.conference_id}.")
                await self.start_conference()
            else:
                self.log_signal.emit(f"[Error]: Failed to join conference {conference_id}.")

    async def quick_join_conference(self):
        async with self.lock:
            message = {'action': 'quickJoin'}
            await self.send_request(message)

            response = await self.read_response()
            if response:
                self.log_signal.emit(str(response))
            if response and response.get('status') == 'success':
                self.conference_id = int(response.get('conference_id'))
                self.DATA_SERVER_PORT_MAPPING = response.get('ports')
                self.on_meeting = True
                self.log_signal.emit(f"Successfully joined conference {self.conference_id}.")
                await self.start_conference()
            else:
                self.log_signal.emit(f"[Error]: Failed to join conference.")

    async def quit_conference(self):
        if not self.on_meeting:
            self.log_signal.emit("[Warn]: You are not in any conference.")
            return
        try:
            for data_type, writer in self.share_data.items():
                if writer:
                    self.share_switch(data_type)
            self.stop_all_tasks()
            client_ids = {}
            for data_type in self.share_data.keys():
                addr = self.data_connections[data_type][1].get_extra_info('sockname')
                client_id = f"{addr[0]}:{addr[1]}"
                client_ids[data_type] = client_id
            message = {'action': 'quit',
                       'conference_id': self.conference_id,
                       'cids': client_ids
                       }
            await self.send_request(message)

            response = await self.read_response()
            if response and response.get('status') == 'success':
                await self.close_data_connections()

                self.on_meeting = False
                self.conference_id = None
                self.is_creator = False
                self.log_signal.emit(f"Successfully quit conference {self.conference_id}.")
        except Exception as e:
            print(e)
            traceback.print_exc()

    async def cancel_conference(self):
        if not self.on_meeting:
            self.log_signal.emit("[Warn]: You are not in any conference.")
            return
        if not self.is_creator:
            self.log_signal.emit("[Warn]: Only the conference creator can cancel the meeting.")
            return
        try:
            self.stop_all_tasks()
            message = {'action': 'cancel', 'conference_id': self.conference_id}
            await self.send_request(message)
            response = await self.read_response()
            if response and response.get('status') == 'success':
                await self.quit_conference()
                self.log_signal.emit(f"Conference {self.conference_id} has been cancelled successfully.")
            else:
                self.log_signal.emit(f"[Error]: Failed to cancel conference {self.conference_id}.")
        except Exception as e:
            print(e)
            traceback.print_exc()

    async def keep_share(self, data_type, send_conn, capture_function, compress=None, fps_or_frequency=30):
        """
        Running task: keep sharing (capture and send) certain type of data from server or clients (P2P).
        """
        if data_type == 'audio':
            fps_or_frequency = 50
        else:
            fps_or_frequency = 20
        while True:
            if not self.on_meeting:  # 没能进入循环
                continue
            captured_data = await capture_function(data_type)
            if captured_data:
                if compress:  # only image data need to be compressed
                    captured_data = compress_image(captured_data, quality=60)
                if isinstance(captured_data, bytes):
                    captured_data = base64.b64encode(captured_data).decode()  # bytes -> b64byte -> str
                message = {
                    'action': 'share',
                    'data_type': data_type,
                    'data': captured_data,
                }
                await self.send_request(message, send_conn)
            # else:
            #     await asyncio.sleep(0.1)
            await asyncio.sleep(1 / fps_or_frequency)  # Control frequency

    def share_switch(self, data_type):
        """
        Switch for sharing a certain type of data (screen, camera, audio, etc.).
        """
        if self.share_data[data_type]:  # -> close
            if data_type == 'screen':
                black = compress_image(Image.open('black.jpg'))
                captured_data = base64.b64encode(black).decode()  # bytes -> b64byte -> str
                message = {
                    'action': 'share',
                    'data_type': data_type,
                    'data': captured_data,
                }
                writer = self.share_data[data_type]
                task = asyncio.create_task(self.send_request(message, writer))

            self.share_data[data_type] = None
            self.log_signal.emit(f"Closed to share {data_type}.")
        else:  # -> open
            reader, writer = self.data_connections.get(data_type, (None, None))
            if reader and writer:
                self.share_data[data_type] = writer
                self.log_signal.emit(f"Switched to share {data_type}.")
                return self.share_data #test
            else:
                self.log_signal.emit(f"[Error]: No data connection available for {data_type}.")

    async def keep_recv(self, recv_conn, data_type, decompress=None):
        """
        Continuously receive data of a certain type (audio, video, etc.) and process it.
        """
        try:
            while self.on_meeting:
                response = await self.read_response(recv_conn)  # response 是一个词典
                if response:
                    if response.get('data_type') == data_type:
                        await self.output_data(response, decompress)
                else:
                    print("[test]No data listen")
                    break
                    # await asyncio.sleep(0)  # 让出控制权
        except asyncio.IncompleteReadError:
            self.log_signal.emit(f"[Info] Connection closed by server for {data_type}.")
        except Exception as e:
            print(e)
            # traceback.print_exc()
            self.log_signal.emit(f"[Error] Failed to receive {data_type} data: {e}")

    async def output_data(self, response, decompress=False):
        """
        Process and output the received stream data.
        For example, play audio or display video.
        """
        data_type = response.get('data_type')
        data = response.get('data')  # str
        if data_type in ('audio', 'video', 'screen'):
            data = base64.b64decode(data.encode())  # str -> b64 -> bytes
        if decompress:
            data = decompress_image(data)

        if data_type == 'audio':
            await self.audio_buffer.put(data)

        elif data_type == 'video':  # video其实应该写成camera
            image_cv = cv2.cvtColor(np.array(data), cv2.COLOR_RGB2BGR)
            if image_cv is not None:
                self.video_frame_signal.emit(image_cv)

        elif data_type == 'text':
            client_id = response.get('client_id')
            if client_id:
                decrypted_text = self.cipher.decrypt(data.encode()).decode()
                times = response.get('time')
                user = client_id.split(":")[1]
                message = f"[{times}]User@{user}: {decrypted_text}"
                self.log_signal.emit(message)  # 显示在消息区域
            else:
                if data == "CANCEL":
                    await self.quit_conference()
                    self.log_signal.emit("Cfec cancel.")
        else:
            self.log_signal.emit(f"Unhandled data type: {data_type}")

    async def play_audio(self):
        buffer = asyncio.Queue(maxsize=10)
        self.audio_buffer = buffer
        while True:
            if not buffer.empty():
                data = await buffer.get()
                audio_block = np.frombuffer(data, dtype=np.int16)
                voice = nr.reduce_noise(audio_block, RATE)
                voice = voice.astype(np.int16).tobytes()
                streamout.write(voice)
            else:
                await asyncio.sleep(0)

    async def start_conference(self):
        """
        Initialize connections when creating or joining a conference, and start necessary running tasks.
        This includes starting tasks for receiving and sharing data.
        """
        if not self.on_meeting:
            self.log_signal.emit("[Error] No active conference.")
            return

        self.log_signal.emit(f"Starting conference {self.conference_id}...")

        # Open separate data connections
        for data_type in self.support_data_types:
            await self.open_data_connection(data_type)

        # 启动接收音频任务
        self.tasks.append(asyncio.create_task(self.play_audio()))

        # Start listening for messages on each data connection
        for data_type, (reader, writer) in self.data_connections.items():
            if reader and writer:
                task = asyncio.create_task(self.keep_recv(
                    reader,
                    data_type,
                    data_type == 'video'))
                self.tasks.append(task)
                # await asyncio.sleep(0)

        # Start sharing tasks for each active data type
        for data_type in self.share_data.keys():
            reader, writer = self.data_connections.get(data_type, (None, None))
            if reader and writer:
                task = asyncio.create_task(self.keep_share(
                    data_type,
                    writer,
                    self.capture_data,
                    data_type in ('video', 'screen')
                ))
                self.tasks.append(task)
                # await asyncio.sleep(0)

        self.log_signal.emit(f"[Dialog] Conference {self.conference_id} is now active.")

    async def capture_data(self, data_type):
        """
        Simulate the process of capturing data (audio, video, etc.).
        Replace this with actual data capture logic.
        """
        if not self.share_data[data_type]:
            return None
        if data_type == 'audio':
            return capture_voice()
        elif data_type == 'video':
            return capture_camera()
        elif data_type == 'screen':
            return capture_screen()

    async def send_text_message(self, message_text):
        """
        Send a text message to the conference.
        """
        if not self.on_meeting:
            self.log_signal.emit("[Warn]: You are not in any conference.")
            return
        encrypt_text = self.cipher.encrypt(message_text.encode()).decode()
        message = {
            'action': 'share',
            'data_type': 'text',
            'data': encrypt_text,
            'encrypt': True,
            'conference_id': self.conference_id
        }
        text_writer = self.data_connections.get('text', (None, None))[1]
        if text_writer:
            await self.send_request(message, text_writer)
        else:
            self.log_signal.emit("[Error]: Text data connection not available.")

    def stop_all_tasks(self):
        """
        Cancel all running tasks.
        """
        try:
            for task in self.tasks:
                task.cancel()
            self.tasks.clear()
        except CancelledError:
            print(f"Handle cancelError")
            # self.writer.write_eof()


if __name__ == '__main__':
    pass
