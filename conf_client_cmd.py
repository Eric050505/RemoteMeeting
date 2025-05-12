# python conf_clientTCP.py
from asyncio import LimitOverrunError

from util import *

class ConferenceClient:
    def __init__(self):
        # Sync client
        # self.is_working = True
        self.server_addr = SERVER_IP  # Server address
        self.on_meeting = False  # Status
        # self.conns = None  # Placeholder if needed for multiple connections
        self.support_data_types = ['text', 'audio', 'video', 'screen']  # Supported data types
        # self.share_data = {}
        self.share_data = { # 存储每一种数据类型的writer
            'video': None,
            'screen': None,
            'audio': None
        }  # Currently shared data types

        # self.conference_info = None  # Conference info
        self.conference_id = None
        # self.recv_data = None  # Received streamed data

        self.is_creator = False
        self.reader = None  # Main command reader
        self.writer = None  # Main command writer
        # self.port = None

        self.data_connections = {}  # data_type: (reader, writer)
        self.DATA_SERVER_PORT_MAPPING = {}

        self.audio_buffer = None
        self.video_buffer = None

    async def open_connection(self):
        """Open the main connection for commands."""
        self.reader, self.writer = await asyncio.open_connection(self.server_addr, MAIN_SERVER_PORT)
        print("Main connection established.")

    async def open_data_connection(self, data_type):
        """
        Open a separate connection for a specific data type.
        """
        try:
            # Assuming each data_type has a unique port or same port differentiated by protocol
            # Replace DATA_SERVER_PORT_aMAPPING with actual port mapping if needed

            port = self.DATA_SERVER_PORT_MAPPING.get(data_type, MAIN_SERVER_PORT)

            reader, writer = await asyncio.open_connection(self.server_addr, port)
            self.data_connections[data_type] = (reader, writer)

            print(f"Data connection for '{data_type}' established on port {port}.")
        except Exception as e:
            print(f"[Error] Failed to open connection for {data_type}: {e}")

    async def close_data_connections(self):
        """Close all data type connections."""
        for data_type, (reader, writer) in self.data_connections.items():
            try:
                writer.close()
                await writer.wait_closed()
                print(f"Data connection for '{data_type}' closed.")
            except Exception as e:
                print(f"[Error] Failed to close connection for {data_type}: {e}")
                traceback.print_exc()
        self.data_connections.clear()


    async def close_conference(self):
        """
        Close all connections to servers or other clients and cancel the running tasks.
        Pay attention to exception handling to ensure graceful shutdown.
        """
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
            print("All conference connections closed and cleaned up.")
        except Exception as e:
            print(f"[Error] Failed to close conference properly: {e}")

    async def send_request(self, message, writer=None):
        """
        Send a request message to the server.
        Ensures that the request is properly formatted and transmitted over the connection.
        """
        # try:
        message_json = json.dumps(message)
        target_writer = writer if writer else self.writer
        if not target_writer:
            print("[Error] No connection established.")
            return
        target_writer.write(message_json.encode() + b'\n')  # Adding newline as delimiter
        try:
            await target_writer.drain()
        except AssertionError as e:
            print(f'[Dialog] Send request failed: {e}')
            pass

        # except Exception as e:
        #     print(f"[Error] Failed to send request: {e}")

    async def read_response(self, reader=None):
        """
        Read and decode the response from the server.
        """
        try:
            target_reader = reader if reader else self.reader
            if not target_reader:
                print("[Error]: No connection established.")
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
            if data:
                return json.loads(data.decode())
            return None
        except Exception as e:
            print(f"[Error] Failed to read response: {e}")
            return None

    async def create_conference(self):
        """
        Create a conference: send create-conference request to server and obtain necessary data.
        """
        message = {'action': 'create'}
        await self.send_request(message)

        response = await self.read_response()
        if response and response.get('status') == 'success':
            self.conference_id = response.get('conference_id')
            self.DATA_SERVER_PORT_MAPPING = response.get('ports')
            self.on_meeting = True
            self.is_creator = True
            print(f"Conference {self.conference_id} created successfully.")
            await self.start_conference()
        else:
            print("[Error]: Failed to create conference.")

    async def join_conference(self, conference_id):
        """
        Join a conference: send join-conference request with given conference_id.
        """
        message = {'action': 'join', 'conference_id': conference_id}
        await self.send_request(message)

        response = await self.read_response()
        print(response)
        if response and response.get('status') == 'success':
            self.conference_id = conference_id
            self.DATA_SERVER_PORT_MAPPING = response.get('ports')
            self.on_meeting = True
            print(f"Successfully joined conference {self.conference_id}.")
            await self.start_conference()
        else:
            print(f"[Error]: Failed to join conference {conference_id}.")

    async def quick_join_conference(self):
        message = {'action': 'quickJoin'}
        await self.send_request(message)

        response = await self.read_response()
        print(response)
        if response and response.get('status') == 'success':
            self.conference_id = int(response.get('conference_id'))
            self.DATA_SERVER_PORT_MAPPING = response.get('ports')
            self.on_meeting = True
            print(f"Successfully joined conference {self.conference_id}.")
            await self.start_conference()
        else:
            print(f"[Error]: Failed to join conference {self.conference_id}.")

    async def quit_conference(self):
        """
        Quit your ongoing conference.
        """
        if not self.on_meeting:
            print("[Warn]: You are not in any conference.")
            return

        message = {'action': 'quit', 'conference_id': self.conference_id}
        await self.send_request(message)

        response = await self.read_response()
        print(response)
        if response and response.get('status') == 'success':
            print(f"Left the conference {self.conference_id}.")
            self.conference_id = None
            self.on_meeting = False
            self.is_creator = False
            await self.close_data_connections()
        else:
            print("[Error]: Failed to quit the conference.")

    async def cancel_conference(self):
        """
        Cancel your ongoing conference (when you are the conference manager).
        """
        if not self.on_meeting:
            print("[Warn]: You are not in any conference.")
            return

        if self.is_creator:
            message = {'action': 'cancel', 'conference_id': self.conference_id}
            await self.send_request(message)

            response = await self.read_response()
            print(response)
            if response and response.get('status') == 'success':
                print(f"Conference {self.conference_id} has been canceled.")
                self.on_meeting = False
                self.conference_id = None
                self.is_creator = False
                await self.close_data_connections()

            else:
                print("[Error]: Failed to cancel the conference.")
        else:
            print("[Warn]: Only the conference creator can cancel the meeting.")

    async def keep_share(self, data_type, send_conn, capture_function, compress=None, fps_or_frequency=30):
        """
        Running task: keep sharing (capture and send) certain type of data from server or clients (P2P).
        """
        # try:
        while self.on_meeting:
            captured_data = await capture_function(data_type)
            if captured_data:
                # print(f"k_sh {captured_data}")OK
                if compress:  # only image data need to be compressed
                    captured_data = compress_image(captured_data)
                if isinstance(captured_data, bytes):
                    captured_data = base64.b64encode(captured_data).decode() # bytes -> b64byte -> str
                message = {
                    'action': 'share',
                    'data_type': data_type,
                    'data': captured_data,
                    'compress': compress,
                    'fps_or_frequency': fps_or_frequency
                } # message类型永远是字典
                await self.send_request(message, send_conn)
            await asyncio.sleep(1 / fps_or_frequency)  # Control frequency
        # except Exception as e:
        #     print(f"[Error] Failed to share {data_type} data: {e}")

    def share_switch(self, data_type):
        """
        Switch for sharing a certain type of data (screen, camera, audio, etc.).
        """
        if self.share_data[data_type]: # -> close
            self.share_data[data_type] = None
            print(f"Closed to share {data_type}.")
        else: # -> open
            reader, writer = self.data_connections.get(data_type)
             # open connection for this data_type
            if reader and writer:
                # Start sharing
                self.share_data[data_type] = writer
                asyncio.create_task(self.keep_share(
                    data_type,
                    writer,
                    self.capture_data,
                    data_type in ('video', 'screen'),
                    fps_or_frequency = 10
                ))
            print(f"Switched to share {data_type}.")

    async def keep_recv(self, recv_conn, data_type, decompress=None):
        """
        Continuously receive data of a certain type (audio, video, etc.) and process it.
        """
        try:
            while self.on_meeting:
                response = await self.read_response(recv_conn)# response 是一个词典
                if response:
                    # print(f"Raw data: {response}")  # 打印原始数据
                    if response.get('data_type') == data_type:
                        await self.output_data(response, decompress)
                else:
                    print("[test]No data listen")
                    await asyncio.sleep(0)  # 让出控制权
        except asyncio.IncompleteReadError:
            print(f"[Info] Connection closed by server for {data_type}.")
        # except Exception as e:
        #     print(f"[Error] Failed to receive {data_type} data: {e}")

    async def output_data(self, response, decompress=False):
        """
        Process and output the received stream data.
        For example, play audio or display video.
        """
        # print(f"out_d {response}")
        data_type = response.get('data_type')
        data = response.get('data') # str
        if data_type in ('audio', 'video', 'screen'):
            data = base64.b64decode(data.encode()) # str -> b64 -> bytes
        if decompress:
            data = decompress_image(data)

        if data_type == 'audio':
            # streamout.write(voice)
            await self.audio_buffer.put(data)

        elif data_type == 'video':
            image_cv = cv2.cvtColor(np.array(data), cv2.COLOR_RGB2BGR)
            # 使用OpenCV展示图像
            cv2.imshow('Conference', image_cv)
            cv2.waitKey(10)

        elif data_type == 'screen':
            pass

        elif data_type == 'text':
            times = response.get('time')
            user = response.get('client_id').split(":")[1]
            print(f"[{times}]User@{user}: {data}")  # [times] User@(Client or Server): message
        else:
            print(f"Unhandled data type: {data_type}")

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
        # try:
        if not self.on_meeting:
            print("[Error] No active conference.")
            return

        print(f"Starting conference {self.conference_id}...")

        # Open separate data connections
        for data_type in self.support_data_types:
            await self.open_data_connection(data_type)

        asyncio.create_task(self.play_audio())
        # asyncio.create_task(self.play_video())
        # Start listening for messages on each data connection
        print(f"[test] data_connections: {self.data_connections}")
        for data_type, (reader, writer) in self.data_connections.items():
            if reader and writer:
                # Start receiving and sharing tasks for each active data type
                asyncio.create_task(self.keep_recv(
                    reader,
                    data_type,
                    data_type == 'video'))
                await asyncio.sleep(0)

        # Start sharing
        for data_type in self.share_data.keys():
            reader, writer = self.data_connections.get(data_type)
            if reader and writer:
                asyncio.create_task(self.keep_share(
                    data_type,
                    writer,
                    self.capture_data,
                    data_type in ('video', 'screen')
                ))
                await asyncio.sleep(0)

        print(f"[Dialog] Conference {self.conference_id} is now active.")
        # except Exception as e:
        #     print(f"[Error] Failed to start conference: {e}")


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

    async def start(self):
        """
        Execute functions based on the command line input.
        """
        while True:
            try:
                await self.open_connection()
                while True:
                    await asyncio.sleep(1)
                    status = 'Free' if not self.on_meeting else f'OnMeeting-{self.conference_id}'
                    cmd_input = await aioconsole.ainput(
                        f'({status}) Please enter an operation (enter "?" for help): ')
                    cmd_input = cmd_input.strip().lower()
                    fields = cmd_input.split(maxsplit=1)
                    recognized = True
                    if len(fields) == 0:
                        pass
                    elif len(fields) == 1:
                        cmd = fields[0]
                        if cmd in ('?', '？'):
                            print(HELP)
                        elif cmd in ('create', 'c'):
                            await self.create_conference()
                        elif cmd in ('quickJoin', 'quj'):
                            await self.quick_join_conference()
                        elif cmd in ('quit', 'q'):
                            await self.quit_conference()
                        elif cmd == 'cancel':
                            await self.cancel_conference()
                        else:
                            recognized = False
                    elif len(fields) == 2:
                        cmd, arg = fields
                        if cmd in ('join', 'j'):
                            input_conf_id = arg
                            if input_conf_id.isdigit():
                                await self.join_conference(input_conf_id)
                            else:
                                print('[Warn]: Input conference ID must be in numeric form.')
                        elif self.on_meeting and cmd in ('switch', 'swi'):
                            data_type = arg
                            if data_type in self.support_data_types:
                                self.share_switch(data_type)
                            else:
                                print(f"[Warn]: Unsupported data type '{data_type}'.")
                        elif self.on_meeting and cmd == 'send': # 文本信息
                            message = {
                                'action': 'share',
                                'data_type': 'text',
                                'data': arg,
                                'compress': None,
                                'conference_id': self.conference_id
                            }
                            _, text_writer = self.data_connections.get('text')
                            await self.send_request(message, text_writer)

                        else:
                            recognized = False
                    else:
                        recognized = False
                    if not recognized:
                        print(f'[Warn]: Unrecognized command "{cmd_input}". Type "?" for help.')

            except (EOFError, KeyboardInterrupt):
                print("\nExiting client.")
                if self.on_meeting:
                    await self.quit_conference()
                await self.close_conference()
                break
            except ConnectionRefusedError:
                print(f"Failed to connect Server, try again.")
            # except Exception as e:
            #     print(f"[Error] An unexpected error occurred: {e}")


if __name__ == '__main__':
    client = ConferenceClient()
    asyncio.run(client.start())
