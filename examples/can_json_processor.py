import ast
import sys
import json
import re
import os
import random
import time
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QLabel, QTextEdit, QMessageBox,
    QLineEdit, QDialog, QShortcut, QToolBar, QMainWindow, QAction,
    QFileDialog
)
from PyQt5.QtCore import QTimer, Qt, QThread, QSize, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QKeySequence, QDragEnterEvent, QDropEvent
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5 import NavigationToolbar2QT as NavigationToolbar

from visualizer import CanNetworkVisualizer
from spammer import PacketSpammer
from vcd_viewer import VcdViewer
from packet_viewer import PacketViewer
from constants import TABLE_STYLE, HEADERS, WIDTHS, COLOR_MAP_BY_CAN_ID
import socket
from numpy import interp
# --- Teensy Socket Worker ---
# class TeensySocketWorker(QObject):
    # data_received = pyqtSignal(str)
    # connection_status = pyqtSignal(bool)

    # def __init__(self, ip, port):
    #     super().__init__()
    #     self.ip = ip
    #     self.port = port
    #     self.running = False

    # def run(self):
    #     import socket

    #     TEENSY_IP = "10.0.0.2"
    #     PORT = 23

    #     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    #         try:
    #             s.connect((TEENSY_IP, PORT))
    #             print(f"Connected to {TEENSY_IP}:{PORT}")
    #             s.sendall((" ").encode())
    #             while True:
    #                 # data = s.recv(128).decode()

    #                 # print(data.strip())
    #                 print(s)


    #         except TimeoutError:
    #             print(f"Connection to {TEENSY_IP}:{PORT} timed out")

    #         except KeyboardInterrupt:
    #             print("\nExited successfully")
    
def unsigned_to_signed(value, bit_width):
    # Calculate the maximum value for the given bit width
    max_value = 2 ** (bit_width - 1)

    # If the value exceeds the signed range, adjust it
    if value >= max_value:
        return value - (2 ** bit_width)
    return value
    
    
    
class TeensyThread(QThread):
    packet_received = pyqtSignal(dict)  # Add this line

    def __init__(self, parent=None):
        super().__init__(parent)
        from queue import Queue
        self._send_queue = Queue()
        self._running = False

    def send_packet(self, packet):
        """Queue a CAN packet for sending. Accepts keys: 'id', 'dlc', 'data'.
        If 'can_id' is present, it will be mapped to 'id'.
        """
        from queue import Full
        if isinstance(packet, dict) and 'id' not in packet and 'can_id' in packet:
            try:
                packet = {
                    'id': int(packet.get('can_id')) if packet.get('can_id') is not None else None,
                    'dlc': int(packet.get('dlc', 8)),
                    'data': packet.get('data', [])
                }
            except Exception:
                pass
        try:
            if packet.get('id') == 67:
                print(f"Sending packet: {packet}")
            self._send_queue.put_nowait(packet)
        except Full:
            pass

    def run(self):
        import socket
        import json
        from queue import Empty
        TEENSY_IP = "10.0.0.2"
        PORT = 23
        last_packets = {}  # Store last data by id
        buffer = ""
        self._running = True
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect((TEENSY_IP, PORT))
                print(f"Connected to {TEENSY_IP}:{PORT}")
                s.settimeout(0.05)
                s.sendall(b" ")
                while self._running:
                    # RX
                    try:
                        chunk = s.recv(128).decode()
                        if chunk:
                            buffer += chunk
                    except socket.timeout:
                        pass

                    while '\r\n' in buffer:
                        data, buffer = buffer.split('\r\n', 1)

                        if not data:
                            continue

                        try:
                            parsed_json = json.loads(data)
                            can_id = parsed_json.get('id')
                            can_data = parsed_json.get('data')
                            if can_id is not None:
                                # Only print if new or data changed
                                test = 0
                                if can_id not in last_packets:
                                    test = 1
                                if (can_id not in last_packets) or (last_packets[can_id] != can_data):
                                    last_packets[can_id] = can_data
                                    if isinstance(can_data, list) and len(can_data) >= 2:
                                        value = (can_data[0] << 8) | can_data[1]
                                        if not hasattr(self, 'decimal_dict'):
                                            self.decimal_dict = {}
                                        self.decimal_dict[can_id] = value
                                        if can_id not in {98, 57, 141, 410, 397, 467, 36, 67} and test == 0:
                                            # print(f"Decimal dict: {self.decimal_dict}")
                                            print("Parsed JSON:", parsed_json)
                                            if can_id in {47, 26, 88}:
                                                value = unsigned_to_signed(value, 16)
                                            if can_id == 131:
                                                value = value / 256
                                            if can_id == 109:
                                                if value == 2:
                                                    value = 1
                                                elif value == 1:
                                                    value = -1
                                                elif value == 0:
                                                    continue
                                            print(f"Data as decimal (16-bit): {value}")
                                            packet = {'can_id': can_id, 'data': value}
                                            self.packet_received.emit(packet) # Changed from self.input_packets.append(packet)
                        except json.JSONDecodeError as e:
                            print("JSON decode error:", e)
                    # TX
                    try:
                        while True:
                            pkt = self._send_queue.get_nowait()
                            if not isinstance(pkt, dict):
                                continue
                            if 'id' not in pkt or pkt['id'] is None:
                                continue
                            # Send exactly like test_eth.py
                            try:
                                s.sendall((json.dumps(pkt, separators=(',', ':')) + '\n').encode())
                            except Exception as e:
                                print(f"Teensy TX error: {e}")
                                break
                    except Empty:
                        pass
            except TimeoutError:
                print(f"Connection to {TEENSY_IP}:{PORT} timed out")
            except KeyboardInterrupt:
                print("\nExited successfully")

class CommandTableWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("CAN Command Packets Table")
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.table = self.parent.create_table()
        self.table.itemDoubleClicked.connect(self.parent.handle_table_double_click)
        self.table.itemClicked.connect(self.handle_item_click)
        layout.addWidget(self.table)

        self.populate_table()

    def handle_item_click(self, item):
        if item.column() == 1:
            item.setFlags(item.flags() | Qt.ItemIsEditable)
            self.table.editItem(item)

    def populate_table(self):
        with open("CAN_ID.json", "r") as f:
            json_data = json.load(f)

        all_packetsC = json_data.get("can_id", {})

        command_packets = {
            can_id: info for can_id, info in all_packetsC.items()
            if isinstance(info, dict) and info.get("level") == "command"
        }

        self.table.setRowCount(len(command_packets))
        for row, (can_id, info) in enumerate(command_packets.items()):
            fields = [
                can_id,                                    # ID
                "0",                                       # Data
                info.get("source", ""),                    # Source
                info.get("execution", ""),                 # Destination
                info.get("name", ""),                      # Name
                "command",                                 # Level
                info.get("type", ""),                      # Type
                str(info.get("period", "")),              # Period
                str(info.get("datasize", "")),            # Data Size
                str(info.get("carlaVar", ""))             # CARLA Var
            ]
            for col, value in enumerate(fields):
                self.table.setItem(row, col, QTableWidgetItem(value))

            color = COLOR_MAP_BY_CAN_ID.get(str(can_id), "#f5f5f5")
            for col in range(self.table.columnCount()):
                self.table.item(row, col).setBackground(QColor(color))

class CanJsonProcessor(QWidget):
    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.initUI()
        self.input_packets = []
        self.all_packets = []
        self.setup_shortcuts()
        # Teensy socket thread/worker
        self.teensy_thread = None
        self.teensy_worker = None
        self.teensy_running = False

    def setup_shortcuts(self):
        self.shortcut_import = QShortcut(QKeySequence('Ctrl+O'), self)
        self.shortcut_import.activated.connect(self.import_json)

        self.shortcut_toggle_tables = QShortcut(QKeySequence('Ctrl+T'), self)
        self.shortcut_toggle_tables.activated.connect(self.toggle_table)

        self.shortcut_toggle_repo = QShortcut(QKeySequence('Ctrl+R'), self)
        self.shortcut_toggle_repo.activated.connect(self.togglerepo_comm)

        self.shortcut_toggle_editor = QShortcut(QKeySequence('Ctrl+E'), self)
        self.shortcut_toggle_editor.activated.connect(self.toggle_json_input)

        self.shortcut_process = QShortcut(QKeySequence('Ctrl+P'), self)
        self.shortcut_process.activated.connect(self.process_json)

        self.shortcut_network = QShortcut(QKeySequence('Ctrl+N'), self)
        self.shortcut_network.activated.connect(self.open_network_visualizer)

        self.shortcut_vcd = QShortcut(QKeySequence('Ctrl+V'), self)
        self.shortcut_vcd.activated.connect(self.open_packet_viewer)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if event.mimeData().urls()[0].toLocalFile().endswith('.json'):
                event.acceptProposedAction()

    def dropEvent(self, event):
        file_path = event.mimeData().urls()[0].toLocalFile()
        with open(file_path, 'r') as f:
            content = f.read()
            self.json_input.setText(content)
        self.process_json()

    def initUI(self):
        self.replay_buffer = None
        self.look_buffer = None
        self.setWindowTitle('GUI FOR CARLA')
        self.setGeometry(100, 100, 1200, 600)

        layout = QVBoxLayout()

        self.setup_toolbar()
        layout.addWidget(self.toolbar)

        self.setup_json_input()
        layout.addWidget(self.json_container)

        self.setup_tables()

        table_layout = QHBoxLayout()
        table_layout.addWidget(self.label_input)
        table_layout.addWidget(self.label_simulator)

        sim_table_simulator_layout = QVBoxLayout()
        sim_table_simulator_layout.addWidget(self.search_box)
        sim_table_simulator_layout.addWidget(self.sim_table_report)
        sim_table_simulator_layout.addWidget(self.sim_table_command)

        # Main table view layout
        table_view_layout = QHBoxLayout()
        table_view_layout.addWidget(self.table)
        table_view_layout.addLayout(sim_table_simulator_layout)

        # Add all layouts to main layout
        layout.addLayout(table_layout)
        layout.addLayout(table_view_layout)
        self.setLayout(layout)

    def setup_toolbar(self):
        self.toolbar = QToolBar()
        self.toolbar.setMovable(False)
        self.toolbar.setIconSize(QSize(32, 32))
        self.toolbar.setStyleSheet("""
            QToolBar {
                spacing: 5px;
                padding: 5px;
                background: #f0f0f0;
                border-bottom: 1px solid #ccc;
            }
            QToolButton {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px;
                background: white;
                min-width: 40px;
                min-height: 40px;
            }
            QToolButton:hover {
                background: #e0e0e0;
            }
            QToolButton:pressed {
                background: #d0d0d0;
            }
        """)

        # Create toolbar buttons
        buttons = [
            ('📂', "Importă fișier JSON (Ctrl+O)", self.import_json),
            ('📊', "Comută tabelul report/command (Ctrl+T)", self.togglerepo_comm),
            ('🚘', "Comută tabelul simulatorului (Ctrl+R)", self.toggle_table),
            ('📝', "Arată/Ascunde editorul de JSON manual (Ctrl+E)", self.toggle_json_input),
            ('🕸️', "Deschide schema CAN (Ctrl+N)", self.open_network_visualizer),
            ('🎲', "Flooding Attack", self.spam_random_packets),
            ('♻️', "Replay Attack", self.replay_last_packet),
            ('📋', "Deschide tabelul de comenzi CAN", self.open_command_table),
            ('🔍', "Vizualizare pachet", self.open_packet_viewer),
            ('🔌', "Start Teensy Thread", self.start_teensy_thread)
        ]

        for icon, tooltip, slot in buttons:
            button = QPushButton(icon, self)
            button.setToolTip(tooltip)
            button.setFont(QFont('Arial', 12))
            button.clicked.connect(slot)
            self.toolbar.addWidget(button)
        self.teensy_button = self.toolbar.widgetForAction(self.toolbar.actions()[-1])

    def setup_json_input(self):
        self.json_container = QWidget()
        json_layout = QVBoxLayout()

        self.json_input = QTextEdit(self)
        self.json_input.setFont(QFont('Arial', 10))
        self.json_input.setPlaceholderText("Introdu JSON-ul aici... (poate fi si neformatat)")
        self.json_input.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 8px;
                selection-background-color: #007bff;
                selection-color: white;
            }
        """)
        self.json_input.setVisible(False)

        self.process_button = QPushButton('⚙️', self)
        self.process_button.setToolTip("Proceseaza continutul JSON")
        self.process_button.setFont(QFont('Arial', 12))
        self.process_button.clicked.connect(self.process_json)
        self.process_button.setVisible(False)

        json_layout.addWidget(self.json_input)
        json_layout.addWidget(self.process_button)

        self.json_container.setLayout(json_layout)

    def setup_tables(self):
        self.search_box = QLineEdit(self)
        self.search_box.setPlaceholderText("🔍 Cauta în tabel...")
        self.search_box.textChanged.connect(self.filter_table)
        self.search_box.setStyleSheet("""
            QLineEdit {
                padding: 5px;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background: white;
            }
            QLineEdit:focus {
                border-color: #007bff;
            }
        """)

        self.label_input = QLabel('📥 Pachete CAN Primite (INPUT)', self)
        self.label_simulator = QLabel('🚗 Pachete CAN Procesate (SIMULATOR)', self)
        for label in [self.label_input, self.label_simulator]:
            label.setStyleSheet("""
                QLabel {
                    font-weight: bold;
                    font-size: 12px;
                }
            """)

        self.table = self.create_table()
        self.sim_table_command = self.create_table()
        self.sim_table_report = self.create_table()

        self.sim_table_command.itemDoubleClicked.connect(self.handle_double_click)
        self.table.itemDoubleClicked.connect(self.handle_double_click)
        self.sim_table_report.itemClicked.connect(self.handle_setup_table_double_click)
        self.sim_table_report.setVisible(False)

    def create_table(self, headers = HEADERS, widths = WIDTHS, style = TABLE_STYLE):
        table = QTableWidget()
        table.setColumnCount(10)
        table.setHorizontalHeaderLabels(headers)
        table.setStyleSheet(style)

        for i, width in enumerate(widths):
            table.setColumnWidth(i, width)

        return table

    def closeEvent(self, event):
        if hasattr(self, 'spammer_thread'):
            self.spammer_worker.running = False
            self.spammer_thread.quit()
            self.spammer_thread.wait()
        if self.teensy_running:
            self.stop_teensy_socket()
        event.accept()


    def populate_row(self, table, row, packet):
        fields = [
            str(packet["can_id"]),
            str(packet.get("data", "N/A")),
            packet.get("src", "N/A"),
            packet.get("dst", "N/A"),
            packet.get("name", "N/A"),
            packet.get("level", "N/A"),
            packet.get("type", "N/A"),
            str(packet.get("period", "N/A")),
            str(packet.get("datasize", "N/A")),
            packet.get("carlaVar", "N/A")
        ]
        for col, value in enumerate(fields):
            table.setItem(row, col, QTableWidgetItem(value))


    def toggle_json_input(self):
        is_visible = not self.json_input.isVisible()
        self.json_input.setVisible(is_visible)
        if is_visible:
            self.process_button.setVisible(True)
        else:
            self.process_button.setVisible(False)


    def import_json(self):
        start = 0
        file_name, _ = QFileDialog.getOpenFileName(self, "Deschide fisier JSON", "", "JSON Files (*.json)")
        if file_name:
            with open(file_name, "r") as f:
                json_content = f.read()
                self.json_input.setText(json_content)
                start = time.time()
            self.process_json()
        end = time.time()
        # print(f"Import JSON took {end - start:.2f} seconds")



    def add_packet_to_table_report(self, packet):
        can_id = str(packet["can_id"])
        row_to_update = -1
        for row in range(self.sim_table_report.rowCount()):
            existing_id = self.sim_table_report.item(row, 0)
            if existing_id and existing_id.text() == can_id:
                row_to_update = row
                break

        if row_to_update == -1:
            row_to_update = self.sim_table_report.rowCount()
            self.sim_table_report.insertRow(row_to_update)
        self.populate_row(self.sim_table_report, row_to_update, packet)

        # Apply row coloring similar to add_packet_to_table
        row_color = COLOR_MAP_BY_CAN_ID.get(packet['can_id'], "#f5f5f5")
        if row_color:
            for col in range(self.sim_table_report.columnCount()):
                item = self.sim_table_report.item(row_to_update, col)
                if item:
                    item.setBackground(QColor(row_color))

        # Network visualizer animation similar to add_packet_to_table
        if hasattr(self, 'network_window') and self.network_window.isVisible():
            src = packet.get("src")
            dst = packet.get("dst")
            can_id_val = packet.get("can_id")
            if src in self.network_window.modules and dst in self.network_window.modules:
                self.network_window.send_packet(src, "CGW", can_id_val)
                QTimer.singleShot(800, lambda dst=dst, can_id=can_id_val: self.network_window.send_packet("CGW", dst, can_id))

        # Update replay buffer
        self.replay_buffer = packet
        # Send to Teensy via running TeensyThread
        if packet.get("level") == "report":# and packet.get("can_id") == "141":
            # Send to Teensy via running TeensyThread
            try:
                if self.teensy_thread is not None and self.teensy_thread.isRunning():
                    tx_payload = self._build_teensy_payload_from_packet(packet)
                    if tx_payload.get('id') is not None:
                        self.teensy_thread.send_packet(tx_payload)
            except Exception as e:
                print(f"Teensy send error: {e}")


    def add_packet_to_table(self, packet):
        if self.all_packets and self.all_packets[-1] == packet:
            return
        self.all_packets.append(packet)
        self.sim_table_command.insertRow(0)
        self.populate_row(self.sim_table_command, 0, packet)
        row_color = COLOR_MAP_BY_CAN_ID.get(packet['can_id'], "#f5f5f5")
        if row_color:
            for col in range(self.sim_table_command.columnCount()):
                item = self.sim_table_command.item(0, col)
                if item:
                    item.setBackground(QColor(row_color))

        if hasattr(self, 'network_window') and self.network_window.isVisible():
            # print(f"Packet {packet['can_id']} from {packet['src']} to {packet['dst']}")

            src = packet.get("src")
            dst = packet.get("dst")
            can_id = packet.get("can_id")
            if src in self.network_window.modules and dst in self.network_window.modules:
                self.network_window.send_packet(src, "CGW", can_id)
                QTimer.singleShot(800, lambda dst=dst, can_id=can_id: self.network_window.send_packet("CGW", dst, can_id))
        self.replay_buffer = packet
        # Send to Teensy via running TeensyThread
        # if packet.get("can_id") == "67":

        try:
            if self.teensy_thread is not None and self.teensy_thread.isRunning():
                tx_payload = self._build_teensy_payload_from_packet(packet)
                if tx_payload.get('id') is not None:
                    self.teensy_thread.send_packet(tx_payload)
        except Exception as e:
            print(f"Teensy send error: {e}")

    def _build_teensy_payload_from_packet(self, packet):
        # Map GUI packet dict to Teensy JSON format
        try:
            can_id_raw = packet.get("can_id")
            can_id = int(can_id_raw) if can_id_raw is not None else None
        except Exception:
            can_id = None
        # Determine data bytes
        data_bytes = []
        payload_data = packet.get("data")
        if isinstance(payload_data, list):
            try:
                data_bytes = [int(x) & 0xFF for x in payload_data][:8]
            except Exception:
                data_bytes = []
        else:
            try:
                value = int(float(payload_data))
                value &= 0xFFFF
                data_bytes = [value & 0xFF, (value >> 8) & 0xFF]
            except Exception:
                data_bytes = []
        # Pad to 8
        if len(data_bytes) < 8:
            data_bytes += [0] * (8 - len(data_bytes))
        else:
            data_bytes = data_bytes[:8]
        return {"id": can_id, "dlc": 8, "data": data_bytes}


    def update_table(self, packets):
        self.sim_table_command.setRowCount(0)

        for packet in packets:
            row_position = self.sim_table_command.rowCount()
            self.sim_table_command.insertRow(row_position)
            self.populate_row(self.sim_table_command, row_position, packet)

            row_color = COLOR_MAP_BY_CAN_ID.get(packet["can_id"], "#f5f5f5")
            if row_color:
                for col in range(self.sim_table_command.columnCount()):
                    item = self.sim_table_command.item(row_position, col)
                    if item:
                        item.setBackground(QColor(row_color))


    def filter_table(self):
        search_text = self.search_box.text().lower()
        filtered_packets = [
            p for p in self.all_packets if
            search_text in str(p["can_id"]).lower() or
            search_text in str(p["data"]).lower() or
            search_text in str(p["src"]).lower() or
            search_text in str(p["dst"]).lower() or
            search_text in str(p["name"]).lower() or
            search_text in str(p["level"]).lower() or
            search_text in str(p["type"]).lower() or
            search_text in str(p["period"]).lower() or
            search_text in str(p["datasize"]).lower() or
            search_text in str(p["carlaVar"]).lower()
        ]
        self.update_table(filtered_packets)

    def toggle_table(self):
        self.table.setVisible(not self.table.isVisible())
        self.label_input.setVisible(not self.label_input.isVisible())

    def togglerepo_comm(self):
        self.sim_table_command.setVisible(not self.sim_table_command.isVisible())
        self.search_box.setVisible(not self.search_box.isVisible())
        self.sim_table_report.setVisible(not self.sim_table_report.isVisible())

    def process_json(self):
        try:
            json_text = self.json_input.toPlainText()
            if not json_text.strip():
                raise ValueError("JSON input is empty")

            try:
                json_data = json.loads(json_text)
            except json.JSONDecodeError:
                json_text = self.fix_json(json_text)
                try:
                    json_data = json.loads(json_text)
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON format: {str(e)}")

            if not isinstance(json_data, dict):
                raise ValueError("JSON data must be a dictionary")

            for can_id, details in json_data.items():
                try:
                    if not isinstance(details, dict):
                        raise ValueError(f"Invalid data format for CAN ID {can_id}")

                    packet = {
                        "can_id": can_id,
                        "src": details.get("source", "N/A"),
                        "dst": details.get("execution", "N/A"),
                        "name": details.get("name", "N/A"),
                        "level": details.get("level", "N/A"),
                        "type": details.get("type", "N/A"),
                        "period": details.get("period", "N/A"),
                        "datasize": details.get("datasize", "N/A"),
                        "carlaVar": details.get("carlaVar", "N/A"),
                        "data": details.get("data", None)
                    }
                    self.add_packet_to_table_receive(packet)
                except Exception as e:
                    QMessageBox.warning(
                        self,
                        "Warning",
                        f"Error processing CAN ID {can_id}: {str(e)}",
                        QMessageBox.Ok
                    )
                    continue

        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to process JSON: {str(e)}",
                QMessageBox.Ok
            )

    def add_packet_to_table_receive(self, packet):
        try:

            required_fields = ["can_id", "src", "dst", "name", "level", "type"]
            missing_fields = [field for field in required_fields if field not in packet]
            if missing_fields:
                raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

            self.table.insertRow(0)
            self.input_packets.append(packet)
            self.populate_row(self.table, 0, packet)

            row_color = COLOR_MAP_BY_CAN_ID.get(packet["can_id"], "#f5f5f5")
            if row_color:
                for col in range(self.table.columnCount()):
                    item = self.table.item(0, col)
                    if item:
                        item.setBackground(QColor(row_color))

            self.look_buffer = packet

            if hasattr(self, 'network_window') and self.network_window.isVisible():
                if packet.get("level") == "command" and packet.get("carlaVar") is not None:
                    src = "Tester"
                    dst = packet.get("dst")
                    can_id = packet["can_id"]
                    self.network_window.send_packet(src, "CGW", can_id)
                    QTimer.singleShot(800, lambda dst=dst, can_id=can_id: self.network_window.send_packet("CGW", dst, can_id))

        except Exception as e:
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to add packet to table: {str(e)}",
                QMessageBox.Ok
            )

    def replay_last_packet(self):
        if self.replay_buffer:
            # print("[Replay Attack] :", self.replay_buffer)
            self.add_packet_to_table_receive(self.replay_buffer)
            print(f"Replay buffer: {self.replay_buffer}")
            self.input_packets.append(self.replay_buffer)
        else:
            QMessageBox.information(self, "Replay", "404")



    def fix_json(self, text):

        if text.endswith("},}"):
            text = text[:-2]
        if text.endswith("},"):
            text = text[:-1]

        if not text.startswith("{"):
            text = "{" + text
        if not text.endswith("},}"):
            text = text + "}"

        # print(text)
        return text

    def open_network_visualizer(self):
        if not hasattr(self, 'network_window') or self.network_window is None:
            self.network_window = CanNetworkVisualizer()
        self.network_window.show()

    def handle_table_double_click(self, item):
        try:
            row = item.row()
            table = item.tableWidget()

            if not all(table.item(row, col) for col in range(10)):
                raise ValueError("Incomplete packet data in table row")

            packet = {
                "can_id": table.item(row, 0).text(),
                "data": table.item(row, 1).text(),
                "src": table.item(row, 2).text(),
                "dst": table.item(row, 3).text(),
                "name": table.item(row, 4).text(),
                "level": table.item(row, 5).text(),
                "type": table.item(row, 6).text(),
                "period": table.item(row, 7).text(),
                "datasize": table.item(row, 8).text(),
                "carlaVar": table.item(row, 9).text()
            }

            if packet["can_id"] in {"109", "440", "457", "423", "433", "131"}:
                try:
                    packet["data"] = ast.literal_eval(packet["data"])
                except (ValueError, SyntaxError) as e:
                    print(f"Warning: Could not parse data for CAN ID {packet['can_id']}: {str(e)}")
                    packet["data"] = "0"  # Default value if parsing fails

            try:
                packet_value = float(packet["data"])
            except (ValueError, TypeError):
                print(f"Invalid data for interp: {packet['data']}, setting default to 0")
                packet["data"] = 0

            self.replay_buffer = packet
            self.replay_last_packet()

        except Exception as e:
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to process table double-click: {str(e)}",
                QMessageBox.Ok
            )

    def spam_random_packets(self):
        try:
            if hasattr(self, 'spammer_thread') and self.spammer_thread.isRunning():
                print("Stopping old thread...")
                self.spammer_worker.running = False
                self.spammer_thread.quit()
                self.spammer_thread.wait()

            self.spammer_thread = QThread()
            self.spammer_worker = PacketSpammer()
            self.spammer_worker.moveToThread(self.spammer_thread)
            self.spammer_worker.packet_generated.connect(self.handle_spammed_packet)
            self.spammer_thread.started.connect(self.spammer_worker.run)
            self.spammer_thread.start()

        except Exception as e:
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to start packet spammer: {str(e)}",
                QMessageBox.Ok
            )

    def handle_spammed_packet(self, packet):
        try:
            if not isinstance(packet, dict):
                raise ValueError("Invalid packet format")

            self.input_packets.append(packet)
            self.add_packet_to_table_receive(packet)

            if hasattr(self, 'network_window') and self.network_window.isVisible():
                dst = packet.get("dst")
                can_id = packet.get("can_id")
                if dst in self.network_window.modules:
                    # print(f"[SPOOF DISPLAY] Tester -> CGW -> {dst} | ID: {can_id}")
                    self.network_window.send_packet("Tester", "CGW", can_id)
                    QTimer.singleShot(800, lambda dst=dst, can_id=can_id: self.network_window.send_packet("CGW", dst, can_id))

        except Exception as e:
            print(f"Error handling spammed packet: {str(e)}")

    def open_command_table(self):
        if not hasattr(self, 'command_table_window') or self.command_table_window is None:
            window = QMainWindow()
            window.setWindowFlags(Qt.Window)
            command_table = CommandTableWindow(parent=self)
            window.setCentralWidget(command_table)
            window.setWindowTitle("CAN Command Packets Table")
            window.resize(1000, 600)
            self.command_table_window = window
        self.command_table_window.show()
        self.command_table_window.raise_()
        self.command_table_window.activateWindow()

    def open_packet_viewer(self):
        try:
            if not hasattr(self, 'look_buffer') or not self.look_buffer:
                raise ValueError("No packet available for viewing")

            self.packet_viewer_window = PacketViewer(self.look_buffer)
            self.packet_viewer_window.show()
        except Exception as e:
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to open packet viewer: {str(e)}",
                QMessageBox.Ok
            )

    def handle_setup_table_double_click(self, item):
        try:
            row = item.row()
            table = item.tableWidget()

            if not all(table.item(row, col) for col in range(10)):
                raise ValueError("Incomplete packet data in table row")

            packet = {
                "can_id": table.item(row, 0).text(),
                "data": table.item(row, 1).text(),
                "src": table.item(row, 2).text(),
                "dst": table.item(row, 3).text(),
                "name": table.item(row, 4).text(),
                "level": table.item(row, 5).text(),
                "type": table.item(row, 6).text(),
                "period": table.item(row, 7).text(),
                "datasize": table.item(row, 8).text(),
                "carlaVar": table.item(row, 9).text()
            }

            self.packet_viewer_window = PacketViewer(packet)
            self.packet_viewer_window.show()

        except Exception as e:
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to open packet viewer: {str(e)}",
                QMessageBox.Ok
            )

    def handle_double_click(self, item):
        try:
            button = QApplication.mouseButtons()

            if button == Qt.LeftButton:
                self.handle_setup_table_double_click(item)
            elif button == Qt.RightButton:
                self.handle_table_double_click(item)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Warning",
                f"Failed to handle double-click: {str(e)}",
                QMessageBox.Ok
            )

    def toggle_teensy_socket(self):
        if not self.teensy_running:
            self.start_teensy_socket()
        else:
            self.stop_teensy_socket()

    # def start_teensy_socket(self):
    #     TEENSY_IP = "10.0.0.2"
    #     PORT = 23
    #     self.teensy_worker = TeensySocketWorker(TEENSY_IP, PORT)
    #     self.teensy_thread = QThread()
    #     self.teensy_worker.moveToThread(self.teensy_thread)
    #     self.teensy_thread.started.connect(self.teensy_worker.run)
    #     self.teensy_worker.connection_status.connect(self.handle_teensy_status)
    #     self.teensy_thread.start()
    #     self.teensy_running = True
    #     print("[Connecting to Teensy...]")
    #     self.teensy_button.setText('⏹️')

    # def stop_teensy_socket(self):
    #     if self.teensy_worker:
    #         self.teensy_worker.running = False
    #     if self.teensy_thread:
    #         self.teensy_thread.quit()
    #         self.teensy_thread.wait()
    #     self.teensy_running = False
    #     print("[Teensy connection stopped]")
    #     self.teensy_button.setText('🔌')

    def handle_teensy_status(self, connected):
        if connected:
            print("[Connected to Teensy]")
        else:
            print("[Disconnected from Teensy]")
            self.stop_teensy_socket()

    def start_teensy_thread(self):
        if self.teensy_thread is None or not self.teensy_thread.isRunning():
            self.teensy_thread = TeensyThread()
            self.teensy_thread.packet_received.connect(self.handle_teensy_packet)
            self.teensy_thread.start()
        else:
            print("Teensy thread already running.")

    def handle_teensy_packet(self, packet):
        can_id = str(packet.get('can_id'))  # Ensure string type
        value = packet.get('data')
        # Load CAN_ID.json info if not already loaded
        if not hasattr(self, 'can_id_info'):
            import json
            with open("CAN_ID.json", "r") as f:
                can_id_json = json.load(f)
            self.can_id_info = can_id_json.get("can_id", {})
        info = self.can_id_info.get(can_id, {}).copy()  # Copy to avoid mutating the original

        # Ensure all required fields exist
        info.setdefault("source", "")
        info.setdefault("execution", "")
        info.setdefault("name", "")
        info.setdefault("level", "")
        info.setdefault("type", "")
        info.setdefault("period", "")
        info.setdefault("datasize", "")
        info.setdefault("carlaVar", "")

        # Add/overwrite the live data and required fields for table
        info["can_id"] = can_id
        info["data"] = value
        info["src"] = info["source"]
        info["dst"] = info["execution"]

        print(f"Received packet: {info}")
        self.add_packet_to_table_receive(info)
        self.input_packets.append(info)



