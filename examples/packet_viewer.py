from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel
)
from PyQt5.QtGui import QColor
import json

from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar
)
from matplotlib.figure import Figure
import matplotlib.patches as patches
from constants import CAN_FIELDS, FIELD_COLORS

class PacketViewer(QDialog):
    def __init__(self, packet):
        super().__init__()
        self.setWindowTitle("CAN Packet Viewer")
        self.resize(1200, 800)

        self.layout = QVBoxLayout(self)
        self.canvas = FigureCanvas(Figure(figsize=(14, 2.5)))
        self.toolbar = NavigationToolbar(self.canvas, self)
        self.layout.addWidget(self.toolbar)
        self.layout.addWidget(self.canvas)

        self.ax1 = self.canvas.figure.add_subplot(111)

        self.table_info_layout = QHBoxLayout()

        self.table = QTableWidget()
        # self.table.setMinimumWidth(self.width() // 2)
        self.table_info_layout.addWidget(self.table, stretch=1)

        # Label for packet info
        self.packet_info_label = QLabel("Packet Information")
        self.packet_info_label.setWordWrap(True)
        # self.packet_info_label.setMinimumWidth(self.width() // 2)
        self.table_info_layout.addWidget(self.packet_info_label, stretch=1)

        # Add to main layout
        self.layout.addLayout(self.table_info_layout)

        self.packet = packet
        self._show_packet()

    def _show_packet(self):
        self.ax1.clear()
        self._plot_binary_representation()
        self._update_field_table()
        self.canvas.draw()

    def _get_field_length(self, field_length):
        if callable(field_length):
            return field_length(int(self.packet.get("datasize", 1)))
        return field_length

    def _update_field_table(self):
        self.table.setRowCount(len(CAN_FIELDS))
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Field", "Binary", "Decimal", "Hex"])

        complete_binary = self._get_complete_binary()
        current_pos = 0
        for row, (field_name, field_length) in enumerate(CAN_FIELDS):
            field_length = self._get_field_length(field_length)
            field_binary = complete_binary[current_pos:current_pos + field_length]
            try:
                decimal_value = int(field_binary, 2)
                hex_value = format(decimal_value, f'0{field_length//4 + (1 if field_length%4 else 0)}x')
            except ValueError:
                decimal_value = 0
                hex_value = '0'

            items = [
                QTableWidgetItem(field_name),
                QTableWidgetItem(field_binary),
                QTableWidgetItem(str(decimal_value)),
                QTableWidgetItem(hex_value)
            ]

            bg_color = QColor(FIELD_COLORS.get(field_name, "#ffffff"))
            for col, item in enumerate(items):
                item.setBackground(bg_color)
                self.table.setItem(row, col, item)

            current_pos += field_length

        self.table.resizeColumnsToContents()
        self.table.setMinimumHeight(300)

        # Display raw packet JSON
        pretty_json = json.dumps(self.packet, indent=2)
        self.packet_info_label.setText(f"""
        <pre style="
            background-color: #f0f0f0;
            border: 1px solid #ccc;
            padding: 10px;
            font-family: Courier New, monospace;
            font-size: 12pt;
            white-space: pre-wrap;
        ">{pretty_json}</pre>
        """)

    def _plot_binary_representation(self):
        self.ax1.set_ylim(-0.5, 3.5)
        self.ax1.set_yticks([0, 1, 2, 3])
        self.ax1.set_yticklabels(['CAN_L 0', 'CAN_L 1', 'CAN_H 0', 'CAN_H 1'])
        self.ax1.grid(True, axis='x', linestyle='--', alpha=0.5)

        complete_binary = self._get_complete_binary()
        total_bits = len(complete_binary)
        
        # Calculate total width needed for the plot
        total_width = 0
        bit_positions = []
        current_pos = 0
        
        for field_name, field_length in CAN_FIELDS:
            field_length = self._get_field_length(field_length)
            if field_name not in ["ESI", "DLC", "DATA", "CRC", "CRC_DELIM"]:
                # Double width
                for i in range(field_length):
                    bit_positions.append(current_pos + i * 2)
                current_pos += field_length * 2
            else:
                # Normal width
                for i in range(field_length):
                    bit_positions.append(current_pos + i)
                current_pos += field_length
            total_width = max(total_width, current_pos)

        self.ax1.set_xlim(-1, total_width)

        prev_can_l = None
        prev_can_h = None

        for i, bit in enumerate(complete_binary):
            can_l = int(bit)
            can_h = 1 - can_l
            pos = bit_positions[i]
            next_pos = bit_positions[i + 1] if i < total_bits - 1 else total_width

            # CAN_L plot
            if prev_can_l is not None and prev_can_l != can_l:
                self.ax1.plot([pos, pos], [prev_can_l, can_l], 'r-', linewidth=1.5)
            self.ax1.plot([pos, next_pos], [can_l, can_l], 'b-', linewidth=1.2)
            prev_can_l = can_l

            # CAN_H plot (shifted to y + 2)
            if prev_can_h is not None and prev_can_h != can_h:
                self.ax1.plot([pos, pos], [prev_can_h + 2, can_h + 2], 'g-', linewidth=1.5)
            self.ax1.plot([pos, next_pos], [can_h + 2, can_h + 2], 'm-', linewidth=1.2)
            prev_can_h = can_h

            if i < total_bits - 1:
                self.ax1.axvline(x=next_pos, color='gray', linestyle='-', alpha=0.2)

        current_pos = 0
        for i, (field_name, field_length) in enumerate(CAN_FIELDS):
            field_length = self._get_field_length(field_length)
            if not isinstance(field_length, int) or field_length <= 0:
                continue

            # Calculate start and end positions for this field
            start_pos = bit_positions[current_pos]
            if field_name == "EOF":
                end_pos = total_width
            elif i < len(CAN_FIELDS) - 1:
                next_field_length = self._get_field_length(CAN_FIELDS[i + 1][1])
                if isinstance(next_field_length, int) and next_field_length > 0:
                    end_pos = bit_positions[current_pos + field_length]
                else:
                    end_pos = bit_positions[current_pos + field_length - 1] + 1
            else:
                end_pos = bit_positions[current_pos + field_length - 1] + 1

            color = FIELD_COLORS.get(field_name, 'lightgray')
            rect = patches.Rectangle((start_pos, -0.5), end_pos - start_pos, 4,
                                     facecolor=color, alpha=0.2, edgecolor='black')
            self.ax1.add_patch(rect)
            label_y = 3.25 if (i % 2 == 0) else -0.35
            self.ax1.text((start_pos + end_pos) / 2, label_y, field_name,
                        ha='center', va='bottom', fontsize=8)

            current_pos += field_length

        self.ax1.set_title("CAN-FD Binary Representation", fontsize=12)
        self.ax1.set_xlabel("Bit Position", fontsize=10)

    def _get_complete_binary(self):
        data_value = self.packet.get("data", 0)
        if data_value == 'None' or data_value is None:
            data_value = 0
        else:
            try:
                data_value = int(data_value)
            except (ValueError, TypeError):
                data_value = 0

        dlc = int(self.packet.get("datasize", 1))
        data_length = dlc * 8

        binary_parts = [
            '0',  # SOF
            format(int(self.packet.get("can_id", 0)), '011b'),  # CAN_ID
            "0", # R1
            '1',  # IDE
            '1',  # EDL
            '0',  # r0
            '1',  # BRS
            '1',  # ESI
            format(dlc, '04b'),  # DLC
            format(data_value, f'0{data_length}b'),
        ]

        crc_bits = self._compute_crc15(''.join(binary_parts))

        binary_parts.append(crc_bits)
        binary_parts.append('1')       # CRC_DELIM
        binary_parts.append('0')       # ACK
        binary_parts.append('1')       # ACK_DELIM
        binary_parts.append('1' * 7)   # EOF

        return ''.join(binary_parts)

    def _compute_crc15(self, data):
        # CRC15 polynomial: x^15 + x^14 + x^10 + x^8 + x^7 + x^4 + x^3 + 1
        POLY = 0x4599  # 0b100010110011001
        crc = 0x0000
        
        for bit in data:
            crc = (crc << 1) | int(bit)
            if crc & 0x8000:
                crc ^= POLY
            crc &= 0x7FFF
        
        return format(crc, '015b')

