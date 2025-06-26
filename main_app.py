import sys
import json
import time
import os
import uuid
import socket
import copy
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGridLayout, QFrame, QDialog, QLineEdit,
    QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
    QFileDialog, QSizePolicy, QListWidget, QListWidgetItem, QGroupBox,
    QRadioButton, QComboBox, QMessageBox, QMenu, QStackedWidget
)
from PySide6.QtCore import Qt, Slot, Signal, QTimer, QObject, QThread
from PySide6.QtGui import QPalette, QColor, QFont, QAction

# =============================================================================
# --- GLOBAL CONFIGURATION ---
# =============================================================================
MQTT_BROKER = "localhost" # Default for transmitter, receiver will load from config
MQTT_PORT = 1883
MQTT_APP_ID = "cuelight_system"
ZEROCONF_SERVICE_TYPE = "_cuelight-mqtt._tcp.local."

ROLE_CONFIG_FILE = "device_role.json"
RECEIVER_CONFIG_FILE = "receiver_config.json"
DEFAULT_SHOW_FILE = "last_show.qlx"

COLOR_OPTIONS_PY = { 
    "White": ("#FFFFFF", "#000000"), "Cyan": ("#00BCD4", "#000000"),
    "Magenta": ("#E91E63", "#FFFFFF"), "Yellow": ("#FFEB3B", "#000000"),
    "Red": ("#F44336", "#FFFFFF"), "Green": ("#4CAF50", "#FFFFFF"),
    "Blue": ("#2196F3", "#FFFFFF"), "Orange": ("#FF9800", "#000000"),
    "Lavender": ("#9575CD", "#FFFFFF"), "Purple": ("#9C27B0", "#FFFFFF"),
    "Teal": ("#009688", "#FFFFFF"),
}
GO_DURATION_MS = 5000

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    print("paho-mqtt library not found. Please install: pip install paho-mqtt")
    MQTT_AVAILABLE = False

try:
    from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceStateChange, BadTypeInNameException
    ZEROCONF_AVAILABLE = True
except ImportError:
    print("zeroconf library not found. Please install: pip install zeroconf")
    ZEROCONF_AVAILABLE = False

# =============================================================================
# --- SHARED MQTT WORKER ---
# =============================================================================
class MqttWorker(QObject):
    connection_status = Signal(bool)
    message_received = Signal(str, str)

    def __init__(self, broker, port, topics_to_subscribe=None):
        super().__init__()
        self.client = None
        self.broker = broker
        self.port = port
        self.topics = topics_to_subscribe or []

    @Slot()
    def run(self):
        if not MQTT_AVAILABLE or not self.broker: return
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        try:
            self.client.connect(self.broker, self.port, 60)
            self.client.loop_forever()
        except Exception as e:
            print(f"MQTT Worker: Could not connect to {self.broker}. {e}")
            self.connection_status.emit(False)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            print("MQTT Worker: Connected.")
            self.connection_status.emit(True)
            if self.topics:
                for topic in self.topics:
                    if topic: client.subscribe(topic); print(f"Subscribed to {topic}")
        else:
            print(f"MQTT Worker: Failed to connect, code {reason_code}"); self.connection_status.emit(False)
    
    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        print(f"MQTT Worker: Disconnected with reason code: {reason_code}"); self.connection_status.emit(False)
    
    def on_message(self, client, userdata, msg):
        self.message_received.emit(msg.topic, msg.payload.decode())
    
    @Slot(str, str)
    def publish(self, topic, payload):
        if self.client and self.client.is_connected():
            self.client.publish(topic, payload)

    @Slot(list)
    def update_subscriptions(self, topics):
        if self.client and self.client.is_connected():
            if self.topics:
                for old_topic in self.topics:
                    if old_topic: self.client.unsubscribe(old_topic)
            for new_topic in topics:
                if new_topic: self.client.subscribe(new_topic)
        self.topics = topics

    @Slot()
    def stop(self):
        if self.client: self.client.loop_stop(); self.client.disconnect()

# =============================================================================
# --- FORWARD DECLARATIONS and GLOBAL WIDGETS ---
# =============================================================================
class TransmitterWindow(QMainWindow): pass
class ReceiverWindow(QMainWindow): pass
class ReceiverSettingsDialog(QDialog): pass

class ChannelColumnWidget(QFrame):
    status_change_requested = Signal(int, str)

    def __init__(self, numeric_id, parent=None):
        super().__init__(parent)
        self.numeric_id = numeric_id
        self.current_status = "idle"
        
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self._update_countdown_display)
        self.countdown_seconds = 0
        
        self._init_ui()

    def _init_ui(self):
        self.setFrameShape(QFrame.Shape.StyledPanel); self.setFrameShadow(QFrame.Shadow.Raised)
        self.setStyleSheet("QFrame { border: 2px solid gray; border-radius: 5px; background-color: rgba(52, 73, 94, 0.5); } QLabel { background: transparent; }")
        layout = QVBoxLayout(self)
        
        self.name_label = QLabel(f"Channel {self.numeric_id}"); font = self.name_label.font(); font.setBold(True); font.setPointSize(12); self.name_label.setFont(font); layout.addWidget(self.name_label, alignment=Qt.AlignCenter)
        
        # New label for Cue Info
        self.cue_info_label = QLabel(""); self.cue_info_label.setStyleSheet("font-size: 9pt; font-style: italic; color: #ecf0f1;"); self.cue_info_label.setAlignment(Qt.AlignCenter); layout.addWidget(self.cue_info_label)

        self.status_label = QLabel("IDLE"); self.status_label.setAlignment(Qt.AlignCenter); self.status_label.setAutoFillBackground(True); self.status_label.setMinimumHeight(30); font = self.status_label.font(); font.setPointSize(11); font.setBold(True); self.status_label.setFont(font); layout.addWidget(self.status_label)
        
        self.btn_master_sb = QPushButton("Master Standby"); self.btn_solo_op = QPushButton("Solo Standby")
        self.btn_master_sb.clicked.connect(self.master_sb_clicked); self.btn_solo_op.clicked.connect(self.solo_op_clicked)
        layout.addWidget(self.btn_master_sb); layout.addWidget(self.btn_solo_op)
        
        subs_header = QLabel("Confirmed Subscribers:"); subs_header.setStyleSheet("font-size: 8pt; color: #bdc3c7;")
        layout.addWidget(subs_header)
        
        self.subscribers_list = QListWidget()
        self.subscribers_list.setStyleSheet("background-color: #2c3e50; border: 1px solid #7f8c8d;")
        layout.addWidget(self.subscribers_list, 1)

    def master_sb_clicked(self):
        if self.current_status == "standby_master": self.status_change_requested.emit(self.numeric_id, "idle")
        else: self.status_change_requested.emit(self.numeric_id, "standby_master")

    def solo_op_clicked(self):
        if self.current_status == "standby_solo": self.status_change_requested.emit(self.numeric_id, "go")
        else: self.status_change_requested.emit(self.numeric_id, "standby_solo")

    @Slot(dict)
    def update_display(self, data):
        self.current_status = data.get("status", "idle")
        label = data.get("label", f"Ch {self.numeric_id}")[:12]
        color_hex = data.get("colorHex", "#CCCCCC")
        text_color_hex = data.get("textColorHex", "#000000")
        confirmed_subscribers = data.get("confirmed_subscribers", [])
        cue_label = data.get("cueLabel", "")

        self.name_label.setText(label); self.name_label.setStyleSheet(f"color: {color_hex}; font-weight: bold;")
        self.setStyleSheet(f"QFrame {{ border: 2px solid {color_hex}; border-radius: 5px; background-color: rgba(52, 73, 94, 0.5); }} QLabel {{ background: transparent; }}")
        
        self.subscribers_list.clear()
        for sub_name in confirmed_subscribers:
            item = QListWidgetItem(sub_name); item.setForeground(QColor(color_hex)); font = item.font(); font.setBold(True); item.setFont(font); self.subscribers_list.addItem(item)
        
        self.btn_master_sb.setText("Master Standby"); self.btn_master_sb.setStyleSheet("background-color: #555; border: 2px outset #E74C3C;")
        self.btn_solo_op.setText("Solo Standby"); self.btn_solo_op.setStyleSheet("background-color: #555; border: 2px outset #E74C3C;")
        
        if self.current_status == "standby_master": self.btn_master_sb.setStyleSheet(f"background-color: {color_hex}; color: {text_color_hex}; border: 2px inset black;")
        elif self.current_status == "standby_solo": self.btn_solo_op.setText("Solo GO"); self.btn_solo_op.setStyleSheet("background-color: #2ECC71; color: black; font-weight: bold;")

        if self.current_status in ["standby_master", "standby_solo", "go"]:
            self.cue_info_label.setText(cue_label)
        else:
            self.cue_info_label.setText("")

        if self.current_status in ["standby_master", "standby_solo"]:
            self.status_label.setText("STANDBY"); self.status_label.setStyleSheet(f"background-color: {color_hex}; color: {text_color_hex}; border-radius: 3px;"); self.countdown_timer.stop()
        elif self.current_status == "go":
            self.countdown_seconds = GO_DURATION_MS // 1000; self.status_label.setText(f"GO! ({self.countdown_seconds})"); self.status_label.setStyleSheet(f"background-color: #E0E0E0; color: black; border-radius: 3px;"); self.countdown_timer.start(1000)
        else:
            self.status_label.setText("IDLE"); self.status_label.setStyleSheet("background-color: #7f8c8d; color: white; border-radius: 3px;"); self.countdown_timer.stop()

    def _update_countdown_display(self):
        self.countdown_seconds -= 1
        if self.countdown_seconds >= 0:
            self.status_label.setText(f"GO! ({self.countdown_seconds})")
        else:
            self.countdown_timer.stop()

class ChannelConfigWidget(QWidget):
    config_save_requested = Signal(dict)
    view_change_requested = Signal(str)
    def __init__(self, channels_data, parent=None):
        super().__init__(parent); self.widgets = {}; self._init_ui(); self.update_config(channels_data) 
    def update_config(self, channels_data):
        self.temp_channels_data = copy.deepcopy(channels_data)
        for i, widget_group in self.widgets.items():
            channel_data = self.temp_channels_data.get(str(i))
            if channel_data:
                widget_group["name_edit"].setText(channel_data.get("label"))
                widget_group["color_combo"].setCurrentText(channel_data.get("colorName"))
    def _init_ui(self):
        main_layout = QVBoxLayout(self); header_label = QLabel("Channel Configuration"); font = header_label.font(); font.setPointSize(16); font.setBold(True); header_label.setFont(font); header_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(header_label); grid_container = QWidget(); grid_layout = QGridLayout(grid_container)
        for i in range(1, 9):
            label_label = QLabel(f"Channel {i} Label:"); name_edit = QLineEdit(); name_edit.setMaxLength(12); color_label = QLabel("Color:"); color_combo = QComboBox()
            for color_name in COLOR_OPTIONS_PY.keys(): color_combo.addItem(color_name)
            self.widgets[i] = {"name_edit": name_edit, "color_combo": color_combo}; grid_layout.addWidget(label_label, i-1, 0); grid_layout.addWidget(name_edit, i-1, 1); grid_layout.addWidget(color_label, i-1, 2); grid_layout.addWidget(color_combo, i-1, 3)
        main_layout.addWidget(grid_container); main_layout.addStretch(); button_layout = QHBoxLayout(); button_layout.addStretch()
        cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(lambda: self.view_change_requested.emit("manual"))
        save_button = QPushButton("Apply and Return"); save_button.setStyleSheet("background-color: #27ae60; font-weight: bold;"); save_button.clicked.connect(self.save_changes)
        button_layout.addWidget(cancel_button); button_layout.addWidget(save_button); main_layout.addLayout(button_layout)
    def save_changes(self):
        for i, widget_group in self.widgets.items():
            new_label = widget_group["name_edit"].text(); new_color_name = widget_group["color_combo"].currentText(); new_color_hex, new_text_color_hex = COLOR_OPTIONS_PY[new_color_name]
            self.temp_channels_data[str(i)]["label"] = new_label; self.temp_channels_data[str(i)]["colorName"] = new_color_name; self.temp_channels_data[str(i)]["colorHex"] = new_color_hex; self.temp_channels_data[str(i)]["textColorHex"] = new_text_color_hex
        self.config_save_requested.emit(self.temp_channels_data)

class CueEditDialog(QDialog):
    def __init__(self, cue_data, all_channels_data, parent=None):
        super().__init__(parent); self.is_new_cue = cue_data is None; self.cue_data = cue_data if cue_data else {"cueNumber": "", "label": "", "channelsInCue": []}
        self.all_channels_data = all_channels_data; self.setWindowTitle("Edit Cue" if not self.is_new_cue else "Add New Cue"); self.setMinimumWidth(400); self.checkboxes = {}; self._init_ui()
    def _init_ui(self):
        layout = QVBoxLayout(self); grid_layout = QGridLayout(); grid_layout.addWidget(QLabel("Cue Number:"), 0, 0); self.num_edit = QLineEdit(str(self.cue_data.get("cueNumber", ""))); grid_layout.addWidget(self.num_edit, 0, 1); grid_layout.addWidget(QLabel("Cue Label:"), 1, 0); self.label_edit = QLineEdit(self.cue_data.get("label", "")); self.label_edit.setMaxLength(30); grid_layout.addWidget(self.label_edit, 1, 1); layout.addLayout(grid_layout)
        channels_group = QGroupBox("Channels in Cue"); channels_layout = QGridLayout(channels_group)
        for i in range(1, 9):
            ch_data = self.all_channels_data.get(str(i));
            if not ch_data: continue
            checkbox = QCheckBox(f"{i}: {ch_data.get('label')}"); 
            if i in self.cue_data.get("channelsInCue", []): checkbox.setChecked(True)
            self.checkboxes[i] = checkbox; row, col = divmod(i - 1, 4); channels_layout.addWidget(checkbox, row, col)
        layout.addWidget(channels_group); self.button_box = QDialogButtonBox(); save_btn = self.button_box.addButton("Save Cue", QDialogButtonBox.ButtonRole.AcceptRole); cancel_btn = self.button_box.addButton("Cancel", QDialogButtonBox.ButtonRole.RejectRole)
        if not self.is_new_cue: delete_btn = self.button_box.addButton("Delete Cue", QDialogButtonBox.ButtonRole.DestructiveRole); delete_btn.setStyleSheet("background-color: #c0392b;"); delete_btn.clicked.connect(self.on_delete)
        save_btn.clicked.connect(self.on_save); cancel_btn.clicked.connect(self.reject); layout.addWidget(self.button_box)
    def on_save(self):
        try: cue_num_float = float(self.num_edit.text())
        except ValueError: QMessageBox.warning(self, "Invalid Input", "Cue Number must be a valid number."); return
        selected_channels = [i for i, checkbox in self.checkboxes.items() if checkbox.isChecked()]
        self.cue_data['cueNumber'] = self.num_edit.text(); self.cue_data['cueNumberFloat'] = cue_num_float; self.cue_data['label'] = self.label_edit.text(); self.cue_data['channelsInCue'] = selected_channels
        if 'id' not in self.cue_data: self.cue_data['id'] = uuid.uuid4().hex
        self.accept()
    def on_delete(self):
        if QMessageBox.question(self, "Delete Cue", f"Are you sure you want to delete Cue {self.cue_data.get('cueNumber')}?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes: self.done(QDialog.DialogCode.DestructiveRole)
    def get_data(self): return self.cue_data

class CueStatusDisplay(QFrame):
    def __init__(self, channels_data, parent=None):
        super().__init__(parent); self.labels = {}; self.setFrameShape(QFrame.Shape.StyledPanel); self.setStyleSheet("QFrame { border: 1px solid #7f8c8d; }"); self._init_ui(channels_data)
    def _init_ui(self, channels_data):
        layout = QGridLayout(self)
        for i in range(1, 9): label = QLabel(f"Ch {i}: IDLE"); label.setAlignment(Qt.AlignCenter); label.setAutoFillBackground(True); label.setMinimumHeight(25); self.labels[i] = label; row, col = divmod(i - 1, 4); layout.addWidget(label, row, col)
        self.update_all(channels_data)
    @Slot(dict)
    def update_all(self, channels_data):
        for i_str, data in channels_data.items():
            if i_str.isdigit(): self.update_single(int(i_str), data)
    @Slot(int, dict)
    def update_single(self, channel_id, data):
        if channel_id not in self.labels: return
        label_widget = self.labels[channel_id]; status = data.get("status", "idle"); label = data.get("label", f"Ch {channel_id}")[:12]; color_hex = data.get("colorHex", "#CCCCCC"); text_color_hex = data.get("textColorHex", "#000000")
        status_text = "STANDBY" if "standby" in status else status.upper(); label_widget.setText(f"{label}: {status_text}")
        bg_hex = "#7f8c8d"; text_hex = "#FFFFFF"
        if "standby" in status: bg_hex, text_hex = color_hex, text_color_hex
        elif status == "go": bg_hex, text_hex = "#E0E0E0", "#000000"
        label_widget.setStyleSheet(f"background-color: {bg_hex}; color: {text_hex}; border: 1px solid black; border-radius: 3px;")

class CueListWidget(QWidget):
    cue_action_requested = Signal(str, object)
    def __init__(self, cues_data, channels_data, parent=None):
        super().__init__(parent); self.channels_data = channels_data; self._init_ui(); self.update_cues(cues_data)
    def _init_ui(self):
        layout = QVBoxLayout(self); self.status_display = CueStatusDisplay(self.channels_data); layout.addWidget(self.status_display)
        header_layout = QHBoxLayout(); header_label = QLabel("Cue List"); font = header_label.font(); font.setPointSize(16); font.setBold(True); header_label.setFont(font)
        header_layout.addWidget(header_label); header_layout.addStretch(); add_cue_btn = QPushButton("Add New Cue"); add_cue_btn.clicked.connect(self.add_new_cue); header_layout.addWidget(add_cue_btn); layout.addLayout(header_layout)
        self.table = QTableWidget(); self.table.setColumnCount(4); self.table.setHorizontalHeaderLabels(["Cue", "Label", "Channels", "Actions"]); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive); self.table.setSortingEnabled(True); layout.addWidget(self.table)
    def update_cues(self, cues_data): self.cues_data = cues_data; self.populate_table()
    def populate_table(self):
        self.cues_data.sort(key=lambda x: float(x.get('cueNumberFloat', x.get('cueNumber', 0))))
        self.table.setRowCount(len(self.cues_data))
        for row, cue in enumerate(self.cues_data):
            cue_num_item = QTableWidgetItem(); cue_num_item.setData(Qt.ItemDataRole.DisplayRole, cue.get('cueNumber')); cue_num_item.setData(Qt.ItemDataRole.UserRole, float(cue.get('cueNumberFloat', 0)))
            self.table.setItem(row, 0, cue_num_item); self.table.setItem(row, 1, QTableWidgetItem(cue.get('label'))); self.table.setItem(row, 2, QTableWidgetItem(", ".join(map(str, cue.get("channelsInCue", [])))))
            edit_btn = QPushButton("Edit"); edit_btn.clicked.connect(lambda checked, c=cue: self.edit_cue(c)); self.table.setCellWidget(row, 3, edit_btn)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    def add_new_cue(self): self.cue_action_requested.emit("add", None)
    def edit_cue(self, cue_data): self.cue_action_requested.emit("edit", cue_data)

# ... (ReceiverWindow implementation follows)

class TransmitterWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Cue Light Transmitter (Offline Mode)"); self.setGeometry(0, 0, 800, 480); self.setStyleSheet("background-color: #2c3e50; color: white;")
        self.channels_data = {}; self.cues = []; self.current_show_filepath = DEFAULT_SHOW_FILE; self.transmitter_id = f"tx_{uuid.uuid4().hex[:8]}"; self.pending_requests = {}; self.current_cue_index = -1; self.is_current_cue_armed = False
        self.setup_mqtt(); self._init_ui(); self.handle_startup_choice()
    def _init_ui(self):
        self.main_widget = QWidget(); main_layout = QVBoxLayout(self.main_widget); self.setCentralWidget(self.main_widget); self._create_menus()
        self.top_nav_widget = self.create_top_nav(); main_layout.addWidget(self.top_nav_widget)
        self.header_widget = self.create_header(); main_layout.addWidget(self.header_widget)
        self.content_stack = QStackedWidget(); main_layout.addWidget(self.content_stack)
        self.manual_view_widget = self.create_manual_view(); self.cues_view_widget = CueListWidget(self.cues, self.channels_data); self.channel_config_widget = ChannelConfigWidget(self.channels_data)
        self.content_stack.addWidget(self.manual_view_widget); self.content_stack.addWidget(self.cues_view_widget); self.content_stack.addWidget(self.channel_config_widget)
        self.cues_view_widget.cue_action_requested.connect(self.handle_cue_action); self.channel_config_widget.config_save_requested.connect(self.on_config_saved); self.channel_config_widget.view_change_requested.connect(self.show_manual_view)
        self.show_manual_view()
    def _create_menus(self):
        menu_bar = self.menuBar(); file_menu = menu_bar.addMenu("&File"); new_action = QAction("&New Show", self); new_action.triggered.connect(self.handle_new_config); file_menu.addAction(new_action); load_action = QAction("&Load Show...", self); load_action.triggered.connect(self.handle_load_config); file_menu.addAction(load_action); save_action = QAction("&Save Show", self); save_action.triggered.connect(lambda: self.save_config()); file_menu.addAction(save_action); save_as_action = QAction("&Save Show As...", self); save_as_action.triggered.connect(self.handle_save_config_as); file_menu.addAction(save_as_action); file_menu.addSeparator(); exit_action = QAction("&Exit", self); exit_action.triggered.connect(self.close); file_menu.addAction(exit_action)
    def handle_startup_choice(self):
        msg_box = QMessageBox(self); msg_box.setWindowTitle("Welcome"); msg_box.setText("Start a new show, load a show, or continue where you left off?"); btn_new = msg_box.addButton("New Show", QMessageBox.ButtonRole.ActionRole); btn_load = msg_box.addButton("Load Show...", QMessageBox.ButtonRole.ActionRole); btn_continue = msg_box.addButton("Continue Last Session", QMessageBox.ButtonRole.AcceptRole); msg_box.exec()
        if msg_box.clickedButton() == btn_new: self.handle_new_config()
        elif msg_box.clickedButton() == btn_load: self.handle_load_config()
        else: self.load_config(DEFAULT_SHOW_FILE)
    def create_top_nav(self):
        nav_widget = QFrame(); nav_layout = QHBoxLayout(nav_widget); nav_widget.setStyleSheet("background-color: #34495e;"); nav_layout.setContentsMargins(5,2,5,2)
        self.btn_manual_mode = QPushButton("Manual"); self.btn_cues_mode = QPushButton("Cues"); self.btn_channel_config = QPushButton("Channel Config")
        self.nav_buttons = [self.btn_manual_mode, self.btn_cues_mode, self.btn_channel_config]
        for btn in self.nav_buttons: btn.setCheckable(True); nav_layout.addWidget(btn)
        self.btn_manual_mode.clicked.connect(self.show_manual_view); self.btn_cues_mode.clicked.connect(self.show_cues_view); self.btn_channel_config.clicked.connect(self.show_channel_config_view)
        return nav_widget
    def create_header(self):
        header_widget = QFrame(); header_layout = QHBoxLayout(header_widget); header_widget.setStyleSheet("background-color: #333; padding: 5px;");
        self.mqtt_status_label = QLabel("MQTT: Disconnected"); header_layout.addWidget(self.mqtt_status_label); header_layout.addStretch()
        self.header_controls_widget = QWidget(); controls_layout = QHBoxLayout(self.header_controls_widget); controls_layout.setContentsMargins(0,0,0,0)
        self.master_go_button = QPushButton("MASTER GO"); self.master_go_button.setStyleSheet("background-color: #4CAF50; color: white; font-size: 14pt; font-weight: bold; padding: 8px;"); self.master_go_button.clicked.connect(self.fire_master_go)
        controls_layout.addWidget(self.master_go_button); separator = QFrame(); separator.setFrameShape(QFrame.Shape.VLine); separator.setFrameShadow(QFrame.Shadow.Sunken); controls_layout.addWidget(separator)
        self.cue_controls_widget = self.create_cue_controls(); controls_layout.addWidget(self.cue_controls_widget); header_layout.addWidget(self.header_controls_widget)
        return header_widget
    def create_cue_controls(self):
        widget = QWidget(); layout = QHBoxLayout(widget); layout.setContentsMargins(0,0,0,0)
        self.btn_prev_cue = QPushButton("<< Prev"); self.btn_prev_cue.clicked.connect(self.prev_cue); layout.addWidget(self.btn_prev_cue)
        self.cue_standby_label = QLabel("Standby Cue: --"); self.cue_standby_label.setStyleSheet("color: #ecf0f1; font-size: 12pt;"); layout.addWidget(self.cue_standby_label)
        self.btn_arm_cue = QPushButton("ARM CUE"); self.btn_arm_cue.setStyleSheet("background-color: #f39c12;"); self.btn_arm_cue.clicked.connect(self.arm_current_cue); layout.addWidget(self.btn_arm_cue)
        self.btn_go_cue = QPushButton("GO CUE"); self.btn_go_cue.setStyleSheet("background-color: #e74c3c; color: white; font-weight: bold;"); self.btn_go_cue.clicked.connect(self.go_current_cue); layout.addWidget(self.btn_go_cue)
        self.btn_next_cue = QPushButton("Next >>"); self.btn_next_cue.clicked.connect(self.next_cue); layout.addWidget(self.btn_next_cue)
        return widget
    def setup_mqtt(self):
        confirmation_topic = f"{MQTT_APP_ID}/confirmations/{self.transmitter_id}"; self.mqtt_thread = QThread(); self.mqtt_worker = MqttWorker(MQTT_BROKER, MQTT_PORT, [confirmation_topic]); self.mqtt_worker.moveToThread(self.mqtt_thread)
        self.mqtt_thread.started.connect(self.mqtt_worker.run); self.mqtt_worker.connection_status.connect(self.update_mqtt_status_indicator); self.mqtt_worker.message_received.connect(self.on_confirmation_received); self.mqtt_thread.start()
    def update_mqtt_status_indicator(self, connected): color = "#4CAF50" if connected else "#F44336"; self.mqtt_status_label.setText(f"MQTT: {'Connected' if connected else 'Disconnected'}"); self.mqtt_status_label.setStyleSheet(f"background-color: {color}; color: white; padding: 2px; border-radius: 3px;")
    @Slot(str, str)
    def on_confirmation_received(self, topic, payload):
        try:
            data = json.loads(payload); request_id = data.get("request_id"); receiver_name = data.get("receiver_name", "Unknown Receiver")
            if request_id in self.pending_requests:
                channel_id = self.pending_requests[request_id]
                if str(channel_id) in self.channels_data:
                    if 'confirmed_subscribers' not in self.channels_data[str(channel_id)]: self.channels_data[str(channel_id)]['confirmed_subscribers'] = []
                    if receiver_name not in self.channels_data[str(channel_id)]['confirmed_subscribers']: self.channels_data[str(channel_id)]['confirmed_subscribers'].append(receiver_name)
                    self.update_all_channel_displays()
        except json.JSONDecodeError as e: print(f"Error decoding confirmation payload: {e}")
    def load_config(self, filepath=None):
        target_file = filepath or DEFAULT_SHOW_FILE
        if os.path.exists(target_file):
            try:
                with open(target_file, 'r') as f: config = json.load(f); self.channels_data = config.get("channels", {}); self.cues = config.get("cues", []); self.current_show_filepath = target_file; print(f"Config loaded from {target_file}")
            except Exception as e: print(f"Error reading {target_file}: {e}. Starting with defaults."); self.create_default_config()
        else:
            self.create_default_config()
        self.cues.sort(key=lambda x: float(x.get('cueNumberFloat', x.get('cueNumber', 0))))
        self.current_cue_index = 0 if self.cues else -1
        for i_str in self.channels_data: self.channels_data[i_str]['status'] = 'idle'; self.channels_data[i_str]['confirmed_subscribers'] = []
        if hasattr(self, 'channel_widgets'): self.update_all_channel_displays(); self.update_cue_header_display()
        self.setWindowTitle(f"Transmitter - {os.path.basename(self.current_show_filepath or 'New Show')}")
    def create_default_config(self):
        self.channels_data = {};
        for i in range(1, 9):
            color_name = list(COLOR_OPTIONS_PY.keys())[i % len(COLOR_OPTIONS_PY)]; bg_hex, text_hex = COLOR_OPTIONS_PY[color_name]
            self.channels_data[str(i)] = {"id": f"channel_{i}", "numericId": i, "label": f"Channel {i}", "colorName": color_name, "colorHex": bg_hex, "textColorHex": text_hex}
        self.cues = []; self.current_show_filepath = None; self.current_cue_index = -1
    def save_config(self, filepath=None):
        target_file = filepath or self.current_show_filepath
        if not target_file: self.handle_save_config_as(); return
        channels_to_save = {k: {k2: v2 for k2, v2 in v.items() if k2 not in ['status', 'confirmed_subscribers']} for k, v in self.channels_data.items()}
        config_to_save = {"channels": channels_to_save, "cues": self.cues, "transmitter_name": self.channels_data.get('transmitter_name', 'CueLight-TX')}
        try:
            with open(target_file, 'w') as f: json.dump(config_to_save, f, indent=4)
            self.current_show_filepath = target_file; self.setWindowTitle(f"Transmitter - {os.path.basename(self.current_show_filepath)}"); print(f"Configuration saved to {target_file}")
        except Exception as e: print(f"Error saving config: {e}")
    def handle_new_config(self): self.create_default_config(); self.update_all_channel_displays(); self.update_cue_header_display(); self.setWindowTitle("Transmitter - New Show*")
    def handle_save_config_as(self):
        filepath, _ = QFileDialog.getSaveFileName(self, "Save Show As", "", "Show Files (*.qlx);;All Files (*)");
        if filepath: self.save_config(filepath)
    def handle_load_config(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Load Show", "", "Show Files (*.qlx);;All Files (*)");
        if filepath: self.load_config(filepath)
    def _update_nav_buttons(self, active_button):
        for btn in self.nav_buttons: btn.setChecked(btn == active_button)
        is_operational = active_button in [self.btn_manual_mode, self.btn_cues_mode]
        self.header_controls_widget.setVisible(is_operational)
    def show_manual_view(self): self._update_nav_buttons(self.btn_manual_mode); self.content_stack.setCurrentWidget(self.manual_view_widget); self.update_all_channel_displays()
    def show_cues_view(self): self._update_nav_buttons(self.btn_cues_mode); self.cues_view_widget.update_cues(self.cues); self.cues_view_widget.status_display.update_all(self.channels_data); self.content_stack.setCurrentWidget(self.cues_view_widget); self.update_cue_header_display()
    def show_channel_config_view(self): self._update_nav_buttons(self.btn_channel_config); self.channel_config_widget.update_config(self.channels_data); self.content_stack.setCurrentWidget(self.channel_config_widget)
    @Slot(dict)
    def on_config_saved(self, new_channels_data):
        self.channels_data = new_channels_data; self.save_config()
        for ch_id_str, ch_data in self.channels_data.items():
            topic = f"{MQTT_APP_ID}/config/channel/{ch_id_str}"; payload = json.dumps({"label": ch_data['label'], "colorHex": ch_data['colorHex']}); self.mqtt_worker.publish(topic, payload)
        self.show_manual_view()
    def create_manual_view(self):
        widget = QWidget(); layout = QGridLayout(widget); self.channel_widgets = {}
        for i in range(1, 9):
            col_widget = ChannelColumnWidget(i); col_widget.status_change_requested.connect(self.handle_status_change); self.channel_widgets[i] = col_widget
            row, col = divmod(i - 1, 4); layout.addWidget(col_widget, row, col)
        return widget
    def update_all_channel_displays(self):
        for i_str, channel_data in self.channels_data.items():
            if not i_str.isdigit(): continue
            i = int(i_str)
            if i in self.channel_widgets: self.channel_widgets[i].update_display(channel_data)
        if hasattr(self, 'cues_view_widget'): self.cues_view_widget.status_display.update_all(self.channels_data)
    @Slot(int, str)
    def handle_status_change(self, numeric_id, new_status):
        numeric_id_str = str(numeric_id)
        if numeric_id_str not in self.channels_data: return
        
        old_status = self.channels_data[numeric_id_str].get('status', 'idle')
        if "standby" in old_status and "standby" not in new_status:
            requests_to_remove = [req_id for req_id, ch_id in self.pending_requests.items() if ch_id == numeric_id]
            for req_id in requests_to_remove:
                del self.pending_requests[req_id]

        self.channels_data[numeric_id_str]['status'] = new_status
        payload_data = self.channels_data[numeric_id_str].copy()
        if "standby" in new_status:
            request_id = uuid.uuid4().hex
            payload_data["request_id"] = request_id
            payload_data["response_topic"] = f"{MQTT_APP_ID}/confirmations/{self.transmitter_id}"
            self.pending_requests[request_id] = numeric_id
        
        if self.current_cue_index != -1:
            payload_data["cueLabel"] = self.cues[self.current_cue_index].get('label', '')

        topic = f"{MQTT_APP_ID}/channel/{numeric_id}/status"
        self.mqtt_worker.publish(topic, json.dumps(payload_data))
        self.update_all_channel_displays()
        if new_status == "go": QTimer.singleShot(GO_DURATION_MS, lambda: self.revert_go_to_idle(numeric_id))
    def revert_go_to_idle(self, numeric_id):
        numeric_id_str = str(numeric_id)
        if self.channels_data.get(numeric_id_str, {}).get('status') == 'go':
            if 'confirmed_subscribers' in self.channels_data[numeric_id_str]:
                self.channels_data[numeric_id_str]['confirmed_subscribers'] = []
            self.handle_status_change(numeric_id, 'idle')
    def fire_master_go(self):
        for i_str, data in self.channels_data.items():
            if data.get('status') == "standby_master": self.handle_status_change(int(i_str), "go")
    def update_cue_header_display(self):
        if self.current_cue_index != -1 and self.cues:
            cue = self.cues[self.current_cue_index]
            self.cue_standby_label.setText(f"Standby Cue: {cue.get('cueNumber')} - {cue.get('label')}")
            color = "#f39c12" if not self.is_current_cue_armed else "#7f8c8d"
            self.btn_arm_cue.setStyleSheet(f"background-color: {color};"); self.btn_arm_cue.setEnabled(not self.is_current_cue_armed); self.btn_go_cue.setEnabled(self.is_current_cue_armed)
        else:
            self.cue_standby_label.setText("Standby Cue: --"); self.btn_arm_cue.setEnabled(False); self.btn_go_cue.setEnabled(False)
    @Slot()
    def arm_current_cue(self):
        if self.current_cue_index == -1 or not self.cues: return
        cue = self.cues[self.current_cue_index]
        for channel_id in cue.get("channelsInCue", []): self.handle_status_change(channel_id, "standby_master")
        self.is_current_cue_armed = True; self.update_cue_header_display()
    @Slot()
    def go_current_cue(self):
        if not self.is_current_cue_armed or self.current_cue_index == -1: return
        cue = self.cues[self.current_cue_index]
        for channel_id in cue.get("channelsInCue", []): self.handle_status_change(channel_id, "go")
        self.is_current_cue_armed = False; self.next_cue()
    @Slot()
    def next_cue(self):
        if len(self.cues) == 0: return
        if self.current_cue_index < len(self.cues) - 1: self.current_cue_index += 1
        else: self.current_cue_index = 0
        self.is_current_cue_armed = False; self.update_cue_header_display()
    @Slot()
    def prev_cue(self):
        if len(self.cues) == 0: return
        if self.current_cue_index > 0: self.current_cue_index -= 1
        else: self.current_cue_index = len(self.cues) - 1
        self.is_current_cue_armed = False; self.update_cue_header_display()
    @Slot(str, object)
    def handle_cue_action(self, action, data):
        if action == "add":
            dialog = CueEditDialog(None, self.channels_data, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                new_cue = dialog.get_data(); self.cues.append(new_cue); self.save_config(); self.show_cues_view()
        elif action == "edit":
            dialog = CueEditDialog(data, self.channels_data, self); result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                updated_cue = dialog.get_data()
                for i, cue in enumerate(self.cues):
                    if cue.get('id') == updated_cue.get('id'): self.cues[i] = updated_cue; break
                self.save_config(); self.show_cues_view()
            elif result == QDialog.DialogCode.DestructiveRole:
                self.cues = [c for c in self.cues if c.get('id') != data.get('id')]; self.save_config(); self.show_cues_view()
    def closeEvent(self, event):
        self.save_config(DEFAULT_SHOW_FILE); self.mqtt_worker.stop(); self.mqtt_thread.quit(); self.mqtt_thread.wait(); super().closeEvent(event)

# =============================================================================
# --- RECEIVER WIDGETS AND WINDOW ---
# =============================================================================
class ReceiverSettingsDialog(QDialog):
    def __init__(self, current_name, current_channel_id, current_broker_ip, parent=None):
        super().__init__(parent); self.setWindowTitle("Receiver Settings"); layout = QVBoxLayout(self)
        name_layout = QHBoxLayout(); name_layout.addWidget(QLabel("Receiver Name:")); self.name_edit = QLineEdit(current_name); self.name_edit.setMaxLength(12); name_layout.addWidget(self.name_edit); layout.addLayout(name_layout)
        channel_layout = QHBoxLayout(); channel_layout.addWidget(QLabel("Subscribe to Channel:")); self.channel_combo = QComboBox(); self.channel_combo.addItems([str(i) for i in range(1, 9)]); self.channel_combo.setCurrentText(str(current_channel_id)); channel_layout.addWidget(self.channel_combo); layout.addLayout(channel_layout)
        broker_layout = QHBoxLayout(); broker_layout.addWidget(QLabel("Broker IP:")); self.broker_edit = QLineEdit(current_broker_ip); broker_layout.addWidget(self.broker_edit); layout.addLayout(broker_layout)
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel); self.button_box.accepted.connect(self.accept); self.button_box.rejected.connect(self.reject); layout.addWidget(self.button_box)
    def get_settings(self): return {"name": self.name_edit.text(), "channel_id": self.channel_combo.currentText(), "broker_ip": self.broker_edit.text()}

class ReceiverWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Cue Light Receiver"); self.setGeometry(100, 100, 800, 480)
        self.current_request_id = None; self.current_response_topic = None; self.is_confirmed = False
        self.broker_ip = "localhost" # Default
        self.load_settings()
        self.setup_mqtt()
        self._init_ui()
    def load_settings(self):
        self.receiver_id = self._get_or_create_receiver_id(); self.receiver_name = "Receiver 1"; self.subscribed_channel_id = 1
        if os.path.exists(RECEIVER_CONFIG_FILE):
            try:
                with open(RECEIVER_CONFIG_FILE, "r") as f: config = json.load(f); self.receiver_name = config.get("name", self.receiver_name); self.subscribed_channel_id = config.get("channel_id", self.subscribed_channel_id); self.broker_ip = config.get("broker_ip", "localhost")
            except Exception as e: print(f"Receiver: Error loading config: {e}")
        self.setWindowTitle(f"Receiver - {self.receiver_name} on Ch {self.subscribed_channel_id}")
    def save_settings(self, name, channel_id, broker_ip):
        self.receiver_name = name; self.subscribed_channel_id = int(channel_id); self.broker_ip = broker_ip
        with open(RECEIVER_CONFIG_FILE, "w") as f: json.dump({"name": self.receiver_name, "channel_id": self.subscribed_channel_id, "broker_ip": self.broker_ip}, f)
        new_topics = [f"{MQTT_APP_ID}/channel/{self.subscribed_channel_id}/status", f"{MQTT_APP_ID}/system/cue_info", f"{MQTT_APP_ID}/config/channel/{self.subscribed_channel_id}"]
        self.mqtt_worker.stop(); self.mqtt_thread.quit(); self.mqtt_thread.wait(); self.setup_mqtt()
        self.setWindowTitle(f"Receiver - {self.receiver_name} on Ch {self.subscribed_channel_id}")
    def _get_or_create_receiver_id(self):
        try:
            with open("receiver_id.txt", "r") as f: return f.read().strip()
        except FileNotFoundError:
            new_id = str(uuid.uuid4());
            with open("receiver_id.txt", "w") as f: f.write(new_id)
            return new_id
    def setup_mqtt(self):
        topics = [f"{MQTT_APP_ID}/channel/{self.subscribed_channel_id}/status", f"{MQTT_APP_ID}/system/cue_info", f"{MQTT_APP_ID}/config/channel/{self.subscribed_channel_id}"]
        self.mqtt_thread = QThread(); self.mqtt_worker = MqttWorker(self.broker_ip, MQTT_PORT, topics); self.mqtt_worker.moveToThread(self.mqtt_thread)
        self.mqtt_thread.started.connect(self.mqtt_worker.run); self.mqtt_worker.message_received.connect(self.handle_mqtt_message); self.mqtt_worker.connection_status.connect(self.update_connection_status); self.mqtt_thread.start()
    def _init_ui(self):
        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget); self.main_layout = QVBoxLayout(self.central_widget); self.main_layout.setAlignment(Qt.AlignCenter)
        self.receiver_name_label = QLabel(self.receiver_name); font_receiver_name = self.receiver_name_label.font(); font_receiver_name.setPointSize(24); self.receiver_name_label.setFont(font_receiver_name); self.main_layout.addWidget(self.receiver_name_label)
        self.cue_info_label = QLabel(""); font_cue_info = self.cue_info_label.font(); font_cue_info.setPointSize(16); self.cue_info_label.setFont(font_cue_info); self.cue_info_label.setAlignment(Qt.AlignCenter); self.cue_info_label.setVisible(False); self.main_layout.addWidget(self.cue_info_label)
        self.status_label = QLabel("IDLE"); font_status = self.status_label.font(); font_status.setPointSize(72); font_status.setBold(True); self.status_label.setFont(font_status); self.status_label.setAlignment(Qt.AlignCenter); self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding); self.main_layout.addWidget(self.status_label, 1)
        self.channel_name_label = QLabel(f"Channel {self.subscribed_channel_id}"); font_ch_name = self.channel_name_label.font(); font_ch_name.setPointSize(16); self.channel_name_label.setFont(font_ch_name); self.channel_name_label.setAlignment(Qt.AlignCenter); self.main_layout.addWidget(self.channel_name_label)
        self.confirm_button = QPushButton("Confirm?"); font_confirm = self.confirm_button.font(); font_confirm.setPointSize(20); font_confirm.setBold(True); self.confirm_button.setFont(font_confirm); self.confirm_button.setMinimumHeight(60); self.confirm_button.clicked.connect(self.handle_confirm_press); self.confirm_button.setVisible(False); self.main_layout.addWidget(self.confirm_button)
        self.settings_button = QPushButton("⚙️"); self.settings_button.setFixedSize(30, 30); self.settings_button.clicked.connect(self.open_settings_dialog); header_layout = QHBoxLayout(); header_layout.addStretch(1); header_layout.addWidget(self.settings_button); self.main_layout.insertLayout(0, header_layout)
        self.update_background_and_text()
    @Slot(str, str)
    def handle_mqtt_message(self, topic, payload):
        try: data = json.loads(payload)
        except json.JSONDecodeError: return
        if f"/channel/{self.subscribed_channel_id}/status" in topic: self.update_display_from_data(data)
        elif f"/config/channel/{self.subscribed_channel_id}" in topic: self.channel_name_label.setText(data.get('label', ''))
    def update_display_from_data(self, data):
        status = data.get("status", "idle"); bg_hex = "#E0E0E0"; text_hex = "#000000"; show_confirm = False
        self.current_request_id = None; self.current_response_topic = None; self.is_confirmed = False
        cue_label = data.get("cueLabel", "")
        self.cue_info_label.setText(cue_label)
        self.cue_info_label.setVisible(bool(cue_label))

        if status in ["standby_master", "standby_solo"]: status_text = "STANDBY"; bg_hex = data.get("colorHex", "#E0E0E0"); text_hex = data.get("textColorHex", "#000000"); show_confirm = True; self.current_request_id = data.get("request_id"); self.current_response_topic = data.get("response_topic")
        elif status == "go": status_text = "GO!"; bg_hex = "#000000"; text_hex = data.get("colorHex", "#FFFFFF")
        else: status_text = "IDLE"; self.cue_info_label.setVisible(False)
        self.status_label.setText(status_text); self.channel_name_label.setText(data.get("label", "")); self.update_background_and_text(bg_hex, text_hex); self.confirm_button.setVisible(show_confirm); self.confirm_button.setEnabled(True); self.confirm_button.setText("Confirm?")
    def handle_confirm_press(self):
        if self.current_response_topic and self.current_request_id and not self.is_confirmed:
            payload = json.dumps({"request_id": self.current_request_id, "receiver_id": self.receiver_id, "receiver_name": self.receiver_name})
            self.mqtt_worker.publish(self.current_response_topic, payload)
            self.is_confirmed = True; self.confirm_button.setText("CONFIRMED!"); self.confirm_button.setEnabled(False); self.confirm_button.setStyleSheet("background-color: #4CAF50; color: white;")
    def update_background_and_text(self, bg_color_hex="#E0E0E0", text_color_hex="#000000"):
        pal = self.central_widget.palette(); pal.setColor(QPalette.ColorRole.Window, QColor(bg_color_hex)); self.central_widget.setAutoFillBackground(True); self.central_widget.setPalette(pal)
        style_str = f"color: {text_color_hex};"; self.status_label.setStyleSheet(style_str); self.channel_name_label.setStyleSheet(style_str); self.cue_info_label.setStyleSheet(style_str)
    def update_connection_status(self, connected):
        if not connected: self.update_background_and_text("#505050"); self.status_label.setText("DISCONNECTED")
    def open_settings_dialog(self):
        dialog = ReceiverSettingsDialog(self.receiver_name, self.subscribed_channel_id, self.broker_ip, self)
        if dialog.exec(): settings = dialog.get_settings(); self.save_settings(settings["name"], settings["channel_id"], settings["broker_ip"])
    def closeEvent(self, event): self.mqtt_worker.stop(); self.mqtt_thread.quit(); self.mqtt_thread.wait(); super().closeEvent(event)

# =============================================================================
# --- UNIFIED STARTUP ---
# =============================================================================
def get_device_role():
    if os.path.exists(ROLE_CONFIG_FILE):
        try:
            with open(ROLE_CONFIG_FILE, 'r') as f: return json.load(f).get("role", "receiver").lower()
        except Exception as e: print(f"Error reading role config: {e}. Defaulting to receiver.")
    return "receiver"

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    role = get_device_role()
    print(f"Device role detected: '{role}'")
    
    if role == "transmitter":
        window = TransmitterWindow()
    else:
        window = ReceiverWindow()
        
    window.show()
    if '--fullscreen' in sys.argv:
        window.showFullScreen()
    
    sys.exit(app.exec())
