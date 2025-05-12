# -- coding: utf-8 --**
# python conf_serverTCP.py
import asyncio
import json
import traceback

from util import *

# Define supported data types
DATA_TYPES = ['text', 'audio', 'video', 'screen']


class ConferenceServer:
    def __init__(self, conference_id, data_ports):
        """
        Initialize a ConferenceServer with a conference ID and data_type ports.

        :param conference_id: Unique identifier for the conference
        :param data_ports: Dictionary mapping data types to their allocated ports
        """
        self.conference_id = conference_id
        self.data_ports = data_ports  # {'text': port1, 'audio': port2, ...}
        self.clients = {data_type: {} for data_type in DATA_TYPES}  # data_type: {client_id: connection}
        self.running = True
        # self.audio_buffers = {}  # 存储每个会议的音频缓冲区
        # self.audio_buffer_timers = {}  # 存储每个会议的计时器

        self.camera_buffer = {}
        # Start servers for each data type
        self.data_servers = {'playVideo': asyncio.create_task(
            self.playVideo()
        )}  # + playVideo
        for data_type, port in self.data_ports.items():
            # Start plain TCP server
            self.data_servers[data_type] = asyncio.create_task(
                self.start_server(data_type, port)
            )

        self.screen_share = None

    async def start_server(self, data_type, port):
        """
        Starts TCP server to handle messages.
        """
        if data_type == 'text':
            server = await asyncio.start_server(
                lambda r, w: self.handle_text_client(r, w, data_type),
                SERVER_IP, port
            )
            print(f"Text server for conference {self.conference_id} started on port {port}.")
        else:
            server = await asyncio.start_server(
                lambda r, w: self.handle_media_client(r, w, data_type),
                SERVER_IP, port
            )
            print(f"Media server for conference {self.conference_id} started on port {port}.")
        async with server:
            await server.serve_forever()

    async def handle_text_client(self, reader, writer, data_type):
        """
        Handles incoming text client connections and relays messages.
        """
        client_id = get_client_id(writer)
        # print(f"Text client {client_id} connected to conference {self.conference_id}.")
        self.clients[data_type][client_id] = writer
        try:
            while self.running:
                data = await reader.readline()
                if not data:
                    break
                # message = data.decode().strip()
                message = json.loads(data.decode().strip())
                content = message.get('data')
                now = time.localtime()
                message = {
                    'data_type': data_type,
                    'client_id': client_id,
                    'data': content,
                    'time': f"{now.tm_hour}:{now.tm_min}"
                }  # from server to client, text
                print(f"[text] message: {message}")
                # Broadcast the message to all other text clients
                await self.broadcast(json.dumps(message), client_id, data_type, forself=True)
        except Exception as e:
            print(f"[Error] Text client {client_id} error: {e}")

    async def handle_media_client(self, reader, writer, data_type):
        """
        Handles incoming media client connections (audio, video, screen).
        """
        client_id = get_client_id(writer)
        # print(f"Text client {client_id} connected to conference {self.conference_id}.")
        self.clients[data_type][client_id] = writer
        # try:
        while self.running:
            # data = await reader.readline()
            data = b''
            while True:
                try:
                    chunk = await reader.readuntil(separator=b'\n')
                    data += chunk.strip()
                    break
                except asyncio.exceptions.LimitOverrunError as e:
                    chunk = await reader.read(e.consumed)
                    data += chunk
                except asyncio.exceptions.IncompleteReadError as e2:
                    await asyncio.sleep(0.1)
            if len(data) == 0:
                break
            message = json.loads(data.decode().strip())
            content = message.get('data')
            # now = time.localtime()
            if data_type == 'audio':
                await self.share_audio(content, client_id)
            elif data_type == 'video':
                await self.handle_video(content, client_id)
            elif data_type == 'screen':
                await self.handle_screen(content, client_id)
            else:
                print(f'Unknown format: {data_type}')
        # except Exception as e:
        #     print(f"[Error] Text client {client_id} error: {e}")

    async def share_audio(self, content, client_id):
        response = {
            'data_type': 'audio',
            'client_id': client_id,
            'data': content,
        }
        await self.broadcast(json.dumps(response), client_id, 'audio')

    async def handle_video(self, content, client_id):
        if client_id not in self.camera_buffer:
            self.camera_buffer[client_id] = asyncio.Queue(maxsize=10)
        con_bytes = base64.b64decode(content.encode())  # str -> b64 -> bytes
        camera = decompress_image(con_bytes)  # bytes -> PIL
        await self.camera_buffer[client_id].put(camera)

    async def handle_screen(self, content, client_id):
        con_bytes = base64.b64decode(content.encode())
        screen_frame = decompress_image(con_bytes)
        self.screen_share = screen_frame

    async def playVideo(self):  # in asyncio.create_task
        while True:
            camera_images = []
            for client, buffer in self.camera_buffer.items():  # PIL
                if not buffer.empty():
                    frame = await buffer.get()
                    camera_images.append(frame)
            if len(camera_images) == 0:
                camera_images = None
            screen = Image.open('black.jpg')
            if self.screen_share:
                screen = self.screen_share
            frame = overlay_camera_images(screen, camera_images)
            # print(camera_images)
            data = compress_image(frame, quality=60)
            content = base64.b64encode(data).decode()
            message = {
                'data_type': 'video',
                'client_id': None,
                'data': content,
            }
            # Broadcast the message to all other text clients
            await self.broadcast(json.dumps(message),
                                 None,
                                 'video',
                                 forself=True)
            await asyncio.sleep(0.05) #让出控制权

    async def broadcast(self, message, sender_id, data_type, forself=False):
        """
        Broadcasts a message to all connected clients except the sender.
        """
        for client_id, writer in list(self.clients[str(data_type)].items()):
            if not forself:
                if client_id and client_id == sender_id:
                    continue
            try:
                # writer.write(f"{sender_id}: {message}\n".encode())
                writer.write(f"{message}\n".encode())
                await writer.drain()
                # print("send msg to " + client_id)
            except Exception as e:
                print(f"[Error] Failed to send message to {client_id}: {e}")
                if client_id in self.clients[str(data_type)]:
                    del self.clients[str(data_type)][client_id]
                    writer.close()
                    await writer.wait_closed()

    async def quit_conference(self, client_id, cid_list, main_writer):
        try:
            for data_type in DATA_TYPES:
                if data_type == 'text':
                    continue
                writer = self.clients[data_type][cid_list[data_type]]
                writer.close()
                await writer.wait_closed()
                # del self.clients[data_type][client_id]
            if cid_list['video'] in self.camera_buffer:
                del self.camera_buffer[cid_list['video']]
            print(f'{client_id} exited conference {self.conference_id}')
            response = {'status': 'success',
                        'conference_id': self.conference_id,}
            main_writer.write((json.dumps(response)+'\n').encode())
            await main_writer.drain()

            print('server handle QUIT fin.')
        except Exception as e:
            print(e, f'q_c')
            traceback.print_exc()

    async def cancel_conference(self, main_writer): #还没测过
        """
        Ends the conference by closing all client connections and stopping servers.
        """
        print(f"Cancelling conference {self.conference_id}...")
        try:
            # Close all data servers
            message = {
                'data_type': 'text',
                'client_id': None,
                'data': 'CANCEL',
                'time': None
            }
            await self.broadcast(json.dumps(message), None, 'text', False)
            await asyncio.sleep(2)
            print(f'snedaok {self.data_servers}')
            for data_type, server_task in self.data_servers.items():
                server_task.cancel()

            #Close all data connections
            for data_type in DATA_TYPES:
                for client_id, writer in self.clients[data_type].items():
                    writer.close()
                    await writer.wait_closed()
                self.clients[data_type].clear()

            response = {'status': 'success',
                        'conference_id': self.conference_id, }
            main_writer.write((json.dumps(response)+"\n").encode())
            await main_writer.drain()
            self.running = False
            print(f"Conference {self.conference_id} has been canceled.")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(e)
            traceback.print_exc()


class MainServer:
    def __init__(self, server_ip, main_port):
        self.server_ip = server_ip
        self.server_port = main_port
        self.conference_servers = {}
        self.pool = PortPool(50000, 60000)  # Expanded port range for multiple conferences
        self.audio_buffers = {}
        self.audio_buffer_timers = {}

    async def create_conference(self, writer):
        """
        Create a new conference by allocating ports for each data type and starting a ConferenceServer.
        """
        conference_id = np.random.randint(10000, 99999)
        self.audio_buffers[str(conference_id)] = []
        self.audio_buffer_timers[str(conference_id)] = None

        allocated_ports = self.pool.get_ports(len(DATA_TYPES))
        if not allocated_ports:
            raise Exception("没有足够的可用端口分配给所有数据类型。")

        data_ports = dict(zip(DATA_TYPES, allocated_ports))

        # Initialize ConferenceServer with allocated ports
        conference_server = ConferenceServer(conference_id, data_ports)
        self.conference_servers[str(conference_id)] = conference_server

        response = {
            "status": "success",
            "conference_id": str(conference_id),
            "ports": data_ports,  # {'text': port1, 'audio': port2, ...}
            "client_id": get_client_id(writer)

        }
        writer.write((json.dumps(response) + "\n").encode())
        await writer.drain()
        # await conference_server.addClient(get_client_id(writer))
        print(f"Conference {conference_id} created with ports: {allocated_ports}")

    async def join_conference(self, conference_id, writer):
        """
        Add a client to an existing conference by providing the necessary ports.
        """
        conference_id_str = str(conference_id)
        if conference_id_str in self.conference_servers:
            conference_server = self.conference_servers[conference_id_str]
            response = {
                "status": "success",
                "conference_id": conference_id_str,
                "ports": conference_server.data_ports,  # {'text': port1, 'audio': port2, ...}
                "client_id": get_client_id(writer)
            }
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
            # await conference_server.addClient(get_client_id(writer))
            print(f"Client joined conference {conference_id}. Provided ports: {conference_server.data_ports}")
        else:
            response = {"status": "error", "message": f"Conference {conference_id} not found."}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
            print(f"[Error] Conference {conference_id} not found.")

    async def quit_conference_handle(self, message, writer):
        """
        Handle a client quitting a conference. (Optional implementation)
        """
        conference_id = message.get('conference_id')
        client_id = get_client_id(writer)
        c_id_str = str(conference_id)
        if c_id_str in self.conference_servers:
            cid_list = message.get('cids')
            conference_server = self.conference_servers[c_id_str]
            await conference_server.quit_conference(client_id, cid_list, writer)
        ######

    async def cancel_conference_handle(self, conference_id, writer):
        """
        Cancel an entire conference, disconnecting all clients and freeing ports.
        """
        conference_id_str = str(conference_id)
        if conference_id_str in self.conference_servers:
            conference_server = self.conference_servers.pop(conference_id_str)
            await conference_server.cancel_conference(writer)
            # Release allocated ports
            for port in conference_server.data_ports.values():
                self.pool.release_ports([port])
        else:
            response = {"status": "error", "message": f"Conference {conference_id} not found."}
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
            print(f"[Error] Conference {conference_id} not found for cancellation.")

    async def request_handler(self, reader, writer):
        """
        Handle incoming requests for creating, joining, quitting, or canceling conferences.
        """
        while True:
            try:
                data = await reader.readline()
                if not data:
                    break  # Connection closed
                message = json.loads(data.decode())
                action = message.get("action")
                print(f"Received action: {action} with message: {message}")

                if action == "create":
                    await self.create_conference(writer)
                elif action == "join":
                    conference_id = message.get("conference_id")
                    if conference_id:
                        await self.join_conference(conference_id, writer)
                    else:
                        response = {"status": "error", "message": "Missing conference_id for join action."}
                        writer.write((json.dumps(response) + "\n").encode())
                        await writer.drain()
                elif action == 'quickJoin':  # 测试用
                    conference_id = int(list(self.conference_servers.items())[0][0])  # 第一个
                    if conference_id:
                        await self.join_conference(conference_id, writer)
                    else:
                        response = {"status": "error", "message": "Missing conference_id for join action."}
                        writer.write((json.dumps(response) + "\n").encode())
                        await writer.drain()
                elif action == "quit":
                    conference_id = message.get("conference_id")
                    if conference_id:
                        await self.quit_conference_handle(message, writer)
                    else:
                        response = {"status": "error", "message": "Missing conference_id for quit action."}
                        writer.write((json.dumps(response) + "\n").encode())
                        await writer.drain()
                elif action == "cancel":
                    conference_id = message.get("conference_id")
                    if conference_id:
                        await self.cancel_conference_handle(conference_id, writer)
                    else:
                        response = {"status": "error", "message": "Missing conference_id for cancel action."}
                        writer.write((json.dumps(response) + "\n").encode())
                        await writer.drain()
                elif action == "share":
                    conference_id = message.get("conference_id")
                    data_type = message.get("data_type")
                    data = message.get("data")

                    if conference_id and data_type and data:
                        conference_id_str = str(conference_id)
                        if conference_id_str in self.conference_servers:
                            conference_server = self.conference_servers[conference_id_str]
                            client_id = get_client_id(writer)
                            print(f"[test]Main broadcast{data}")
                            await conference_server.broadcast(data, client_id, data_type)
                        else:
                            response = {"status": "error", "message": f"Conference {conference_id} not found."}
                            writer.write((json.dumps(response) + "\n").encode())
                            await writer.drain()
                            print(f"[Error] Conference {conference_id} not found.")
                else:
                    response = {"status": "error", "message": f"Unknown action: {action}"}
                    writer.write((json.dumps(response) + "\n").encode())
                    await writer.drain()
            except json.JSONDecodeError:
                response = {"status": "error", "message": "Invalid JSON format."}
                writer.write((json.dumps(response) + "\n").encode())
                await writer.drain()
                print("[Error] Received invalid JSON.")
            except ConnectionResetError as cre:
                print('cre ', cre)
                traceback.print_exc()
            except RuntimeError as re:
                print('我能怎么办，我也很绝望')
                print(reader, writer)
                break
            except Exception as e:
                print(f"[Error] Exception in request handler: {str(e)}")
                traceback.print_exc()

        # Close the connection if the client disconnects
        writer.close()
        await writer.wait_closed()
        print("Closed connection with client.")


    async def server_task(self):
        """
        Coroutine that starts the asyncio server.
        """
        server = await asyncio.start_server(self.request_handler, self.server_ip, self.server_port)
        print(f"Main server started on {self.server_ip}:{self.server_port}")
        async with server:
            await server.serve_forever()

def get_client_id(writer):
    addr = writer.get_extra_info('peername')
    client_id = f"{addr[0]}:{addr[1]}"
    return client_id


if __name__ == '__main__':
    # Initialize and start the main server
    main_server = MainServer(SERVER_IP, MAIN_SERVER_PORT)
    asyncio.run(main_server.server_task())

