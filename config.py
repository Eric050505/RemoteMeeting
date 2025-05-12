HELP = 'Create         : create an conference\n' \
       'Join [conf_id ]: join a conference with conference ID\n' \
       'Quit           : quit an on-going conference\n' \
       'Cancel         : cancel your on-going conference (only the manager)\n\n'

HELP2 = 'send [message]\n'\
        'switch [audio/screen/video]\n'\
        'cancel\n'\
        'quit\n\n'

SERVER_IP = '127.0.0.1'
MAIN_SERVER_PORT = 8888
TIMEOUT_SERVER = 5
# DGRAM_SIZE = 1500  # UDP
LOG_INTERVAL = 2

CHUNK = 1024 # 单个音频块数据的大小
CHANNELS = 1  # Channels for audio capture
RATE = 44100  # Sampling rate for audio capture

camera_width, camera_height = 480, 480  # resolution for camera capture
