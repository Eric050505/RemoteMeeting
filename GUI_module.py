import sys
import asyncio
import json
import base64
from PyQt5 import QtWidgets, QtCore, QtGui
from qasync import QEventLoop, asyncSlot
import cv2
import numpy as np


from GUI_client import ConferenceClient

# 定义ConferenceClient类，修改以适应GUI
# 定义GUI类
class ConferenceGUI(QtWidgets.QMainWindow):
    def __init__(self, client: ConferenceClient):
        super().__init__()
        self.client = client
        self.client.log_signal.connect(self.append_log)
        self.client.video_frame_signal.connect(self.update_video_frame)
        self.init_ui()
        self.show()
        # 使用 QTimer.singleShot 延迟任务调度，确保事件循环已启动
        QtCore.QTimer.singleShot(0, lambda: asyncio.create_task(self.initialize_connection()))

    def init_ui(self):
        self.setWindowTitle("线上会议客户端")
        self.setGeometry(100, 100, 800, 600)

        # 主布局
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout()
        central_widget.setLayout(main_layout)

        # 状态显示
        self.status_label = QtWidgets.QLabel("状态: Free")
        main_layout.addWidget(self.status_label)

        # 按钮布局
        button_layout = QtWidgets.QHBoxLayout()

        self.create_button = QtWidgets.QPushButton("创建会议")
        self.create_button.clicked.connect(self.on_create_conference)
        button_layout.addWidget(self.create_button)

        self.join_button = QtWidgets.QPushButton("加入会议")
        self.join_button.clicked.connect(self.on_join_conference)
        button_layout.addWidget(self.join_button)

        self.quick_join_button = QtWidgets.QPushButton("快速加入")
        self.quick_join_button.clicked.connect(self.on_quick_join)
        button_layout.addWidget(self.quick_join_button)

        self.quit_button = QtWidgets.QPushButton("退出会议")
        self.quit_button.clicked.connect(self.on_quit_conference)
        button_layout.addWidget(self.quit_button)

        self.cancel_button = QtWidgets.QPushButton("取消会议")
        self.cancel_button.clicked.connect(self.on_cancel_conference)
        button_layout.addWidget(self.cancel_button)

        main_layout.addLayout(button_layout)

        # 分享控制
        share_layout = QtWidgets.QHBoxLayout()
        self.share_video_button = QtWidgets.QPushButton("分享视频")
        self.share_video_button.setCheckable(True)
        self.share_video_button.clicked.connect(lambda: self.on_share_toggle('video'))
        share_layout.addWidget(self.share_video_button)

        self.share_audio_button = QtWidgets.QPushButton("分享音频")
        self.share_audio_button.setCheckable(True)
        self.share_audio_button.clicked.connect(lambda: self.on_share_toggle('audio'))
        share_layout.addWidget(self.share_audio_button)

        self.share_screen_button = QtWidgets.QPushButton("分享屏幕")
        self.share_screen_button.setCheckable(True)
        self.share_screen_button.clicked.connect(lambda: self.on_share_toggle('screen'))
        share_layout.addWidget(self.share_screen_button)

        main_layout.addLayout(share_layout)

        # 视频显示区域
        self.video_label = QtWidgets.QLabel()
        self.video_label.setFixedSize(640, 480)
        self.video_label.setStyleSheet("background-color: black;")
        main_layout.addWidget(self.video_label)

        # 消息显示区域
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        main_layout.addWidget(self.log_text)

        # 消息输入区域
        message_layout = QtWidgets.QHBoxLayout()
        self.message_input = QtWidgets.QLineEdit()
        self.message_input.setPlaceholderText("输入消息...")
        message_layout.addWidget(self.message_input)
        self.send_button = QtWidgets.QPushButton("发送")
        self.send_button.clicked.connect(self.on_send_message)
        message_layout.addWidget(self.send_button)
        main_layout.addLayout(message_layout)

    async def initialize_connection(self):
        """
        初始化时建立与服务器的连接
        """
        try:
            await self.client.open_connection()
        except ConnectionRefusedError:
            await self.initialize_connection()
        # 如果需要在初始化时自动加入会议，可以在这里添加逻辑
        # 例如：
        # await self.client.quick_join_conference()
        # if self.client.on_meeting:
        #     self.status_label.setText(f"状态: OnMeeting - {self.client.conference_id}")

    @asyncSlot()
    async def on_create_conference(self):
        await self.client.create_conference()
        if self.client.on_meeting:
            self.status_label.setText(f"状态: OnMeeting - {self.client.conference_id}")

    @asyncSlot()
    async def on_join_conference(self):
        conference_id, ok = QtWidgets.QInputDialog.getText(self, "加入会议", "请输入会议ID:")
        if ok and conference_id:
            await self.client.join_conference(conference_id)
            if self.client.on_meeting:
                self.status_label.setText(f"状态: OnMeeting - {self.client.conference_id}")

    @asyncSlot()
    async def on_quick_join(self):
        await self.client.quick_join_conference()
        if self.client.on_meeting:
            self.status_label.setText(f"状态: OnMeeting - {self.client.conference_id}")

    @asyncSlot()
    async def on_quit_conference(self):
        if self.client.is_creator:
            await self.client.cancel_conference()
        else:
            await self.client.quit_conference()
        if not self.client.on_meeting:
            self.status_label.setText("状态: Free")

    @asyncSlot()
    async def on_cancel_conference(self):
        await self.client.cancel_conference()
        if not self.client.on_meeting:
            self.status_label.setText("状态: Free")


    @QtCore.pyqtSlot(str)
    def append_log(self, message):
        self.log_text.append(message)
        if "OnMeeting" in message:
            # 更新状态标签
            parts = message.split("-")
            if len(parts) > 1:
                conf_id = parts[1].strip().replace('.', '')
                self.status_label.setText(f"状态: OnMeeting - {conf_id}")

    @QtCore.pyqtSlot(np.ndarray)
    def update_video_frame(self, frame):
        """将接收到的视频帧显示在视频标签中"""
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        bytes_per_line = ch * w
        qt_image = QtGui.QImage(rgb_image.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
        pixmap = QtGui.QPixmap.fromImage(qt_image).scaled(
            self.video_label.width(),
            self.video_label.height(),
            QtCore.Qt.KeepAspectRatio
        )
        self.video_label.setPixmap(pixmap)

    def on_share_toggle(self, data_type):
        """
        处理分享按钮的切换，使用 asyncio.create_task 调度异步调用
        """
        asyncio.create_task(self.handle_share_toggle(data_type))

    async def handle_share_toggle(self, data_type):
        self.client.share_switch(data_type)
        # 根据按钮状态更新按钮文本
        button_map = {
            'video': self.share_video_button,
            'audio': self.share_audio_button,
            'screen': self.share_screen_button
        }
        button = button_map.get(data_type)
        if button:
            if button.isChecked():
                button.setText(f"停止分享{data_type.capitalize()}")
            else:
                button.setText(f"分享{data_type.capitalize()}")

    @asyncSlot()
    async def on_send_message(self):
        message_text = self.message_input.text().strip()
        if message_text:
            await self.client.send_text_message(message_text)
            self.message_input.clear()

    def closeEvent(self, event):
        """处理窗口关闭事件，确保连接关闭"""
        asyncio.create_task(self.close_client())
        event.accept()

    async def close_client(self):
        if self.client.on_meeting:
            await self.client.quit_conference()
        await self.client.close_conference()



# 主函数
def main():
    app = QtWidgets.QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    client = ConferenceClient()
    gui = ConferenceGUI(client)

    with loop:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
