import base64
import json
import os.path as osp
from PIL import Image

from PyQt5 import QtWidgets
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QVBoxLayout,
    QProgressDialog,
    QDialog,
    QLabel,
    QLineEdit,
    QDialogButtonBox,
    QApplication,
    QSpinBox,
    QHBoxLayout,
)

from anylabeling.app_info import __version__
from anylabeling.services.auto_labeling import (
    _BATCH_PROCESSING_INVALID_MODELS,
    _BATCH_PROCESSING_TEXT_PROMPT_MODELS,
    _BATCH_PROCESSING_VIDEO_MODELS,
)
from anylabeling.views.labeling.logger import logger
from anylabeling.views.labeling.utils._io import io_open
from anylabeling.views.labeling.utils.qt import new_icon_path
from anylabeling.views.labeling.utils.style import get_msg_box_style
from anylabeling.views.labeling.widgets.popup import Popup


__all__ = ["run_all_images"]


class TextInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle(self.tr("Enter Text Prompt"))
        self.setFixedSize(400, 180)
        self.setWindowFlags(Qt.Dialog | Qt.MSWindowsFixedSizeDialogHint)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        prompt_label = QLabel(self.tr("Please enter your text prompt:"))
        prompt_label.setStyleSheet(
            "font-size: 13px; color: #1d1d1f; font-weight: 500;"
        )
        layout.addWidget(prompt_label)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText(self.tr("Enter prompt here..."))
        layout.addWidget(self.text_input)

        button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #ffffff;
                border-radius: 10px;
            }
            
            QLineEdit {
                border: 1px solid #E5E5E5;
                border-radius: 8px;
                background-color: #F9F9F9;
                font-size: 13px;
                height: 36px;
                padding: 0 12px;
            }
            
            QLineEdit:hover {
                background-color: #DBDBDB;
            }
            
            QLineEdit:focus {
                border: 2px solid #0066FF;
                background-color: #F9F9F9;
            }
            
            QPushButton {
                min-width: 100px;
                height: 36px;
                border-radius: 8px;
                font-weight: 500;
                font-size: 13px;
            }
            
            QPushButton[text="OK"] {
                background-color: #0066FF;
                color: white;
                border: none;
            }
            
            QPushButton[text="OK"]:hover {
                background-color: #0077ED;
            }
            
            QPushButton[text="OK"]:pressed {
                background-color: #0068D0;
            }
            
            QPushButton[text="Cancel"] {
                background-color: #f5f5f7;
                color: #1d1d1f;
                border: 1px solid #d2d2d7;
            }
            
            QPushButton[text="Cancel"]:hover {
                background-color: #e5e5e5;
            }
            
            QPushButton[text="Cancel"]:pressed {
                background-color: #d5d5d5;
            }
        """
        )

    def get_input_text(self):
        if self.exec_() == QDialog.Accepted:
            return self.text_input.text().strip()
        return ""

class RangeSelectDialog(QDialog):
    """选择批处理范围（按索引/序号）"""

    def __init__(self, parent=None, total_images: int = 0, default_start: int = 0, default_end: int = 0):
        super().__init__(parent)
        self.total_images = max(0, int(total_images))
        self.default_start = int(default_start)
        self.default_end = int(default_end)
        self._start_index = None
        self._end_index = None
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle(self.tr("选择批量处理范围"))
        self.setWindowFlags(Qt.Dialog | Qt.MSWindowsFixedSizeDialogHint)
        self.setFixedSize(420, 200)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        tip = QLabel(self.tr("请选择要处理的图片范围（包含起止）："))
        layout.addWidget(tip)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel(self.tr("起始（序号）")))
        self.spin_start = QSpinBox()
        self.spin_start.setMinimum(1 if self.total_images > 0 else 0)
        self.spin_start.setMaximum(self.total_images if self.total_images > 0 else 0)
        self.spin_start.setValue(max(1, self.default_start + 1) if self.total_images > 0 else 0)
        row1.addWidget(self.spin_start, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel(self.tr("结束（序号）")))
        self.spin_end = QSpinBox()
        self.spin_end.setMinimum(1 if self.total_images > 0 else 0)
        self.spin_end.setMaximum(self.total_images if self.total_images > 0 else 0)
        self.spin_end.setValue(max(1, self.default_end + 1) if self.total_images > 0 else 0)
        row2.addWidget(self.spin_end, 1)
        layout.addLayout(row2)

        # 约束：start <= end
        def _sync_end_min(v):
            if self.total_images <= 0:
                return
            self.spin_end.setMinimum(v)
            if self.spin_end.value() < v:
                self.spin_end.setValue(v)

        def _sync_start_max(v):
            if self.total_images <= 0:
                return
            self.spin_start.setMaximum(v)
            if self.spin_start.value() > v:
                self.spin_start.setValue(v)

        self.spin_start.valueChanged.connect(_sync_end_min)
        self.spin_end.valueChanged.connect(_sync_start_max)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self._accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

        # 初始化互相约束
        _sync_end_min(self.spin_start.value())
        _sync_start_max(self.spin_end.value())

    def _accept(self):
        if self.total_images <= 0:
            self.reject()
            return
        self._start_index = int(self.spin_start.value()) - 1
        self._end_index = int(self.spin_end.value()) - 1
        self.accept()

    def get_range(self):
        if self.exec_() == QDialog.Accepted:
            return self._start_index, self._end_index
        return None, None

def get_image_size(image_path):
    with Image.open(image_path) as img:
        return img.size


def finish_processing(self, progress_dialog):
    target_index = self.current_index
    target_file = self.image_list[self.current_index]
    self.import_image_folder(osp.dirname(target_file), load=False)
    self.file_list_widget.setCurrentRow(target_index)

    del self.text_prompt
    del self.run_tracker
    del self.image_index
    del self.current_index
    if hasattr(self, "_batch_roi"):
        del self._batch_roi
    # ✅ 新增：清理范围
    if hasattr(self, "_batch_start_index"):
        del self._batch_start_index
    if hasattr(self, "_batch_end_index"):
        del self._batch_end_index

    progress_dialog.close()

    popup = Popup(
        self.tr("Processing completed successfully!"),
        self,
        icon=new_icon_path("copy-green", "svg"),
    )
    popup.show_popup(self, position="center")


def cancel_operation(self):
    self.cancel_processing = True


def save_auto_labeling_result(self, image_file, auto_labeling_result):
    try:
        label_file = osp.splitext(image_file)[0] + ".json"
        if self.output_dir:
            label_file = osp.join(self.output_dir, osp.basename(label_file))

        if auto_labeling_result is None:
            new_shapes = []
            new_description = ""
            replace = True
        else:
            new_shapes = [
                shape.to_dict() for shape in auto_labeling_result.shapes
            ]
            new_description = auto_labeling_result.description
            replace = auto_labeling_result.replace

        if osp.exists(label_file):
            with io_open(label_file, "r") as f:
                data = json.load(f)

            if replace:
                data["shapes"] = new_shapes
                data["description"] = new_description
            else:
                data["shapes"].extend(new_shapes)
                if "description" in data:
                    data["description"] += new_description
                else:
                    data["description"] = new_description
        else:
            if self._config["store_data"]:
                with open(image_file, "rb") as f:
                    image_data = f.read()
                image_data = base64.b64encode(image_data).decode("utf-8")
            else:
                image_data = None

            image_path = osp.basename(image_file)
            image_width, image_height = get_image_size(image_file)

            data = {
                "version": __version__,
                "flags": {},
                "shapes": new_shapes,
                "imagePath": image_path,
                "imageData": image_data,
                "imageHeight": image_height,
                "imageWidth": image_width,
                "description": new_description,
            }

        with io_open(label_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.error(
            f"Failed to save auto labeling result for image file '{image_file}': {str(e)}"
        )


def process_next_image(self, progress_dialog, batch=True):
    total_images = len(self.image_list)
    self._progress_dialog = progress_dialog

    start_i = int(getattr(self, "_batch_start_index", 0))
    end_i = int(getattr(self, "_batch_end_index", total_images - 1))

    try:
        while (self.image_index <= end_i) and (self.image_index < total_images) and (not self.cancel_processing):
            image_file = self.image_list[self.image_index]

            # ✅ UI 不要卡死（吸收 origin/main）
            QApplication.processEvents()

            model_type = self.auto_labeling_widget.model_manager.loaded_model_config["type"]
            batch_processing_mode = "default"

            if model_type == "remote_server":
                model = self.auto_labeling_widget.model_manager.loaded_model_config["model"]
                if hasattr(model, "get_batch_processing_mode"):
                    batch_processing_mode = model.get_batch_processing_mode()
                if batch_processing_mode == "video":
                    model._widget = self
                    if self.run_tracker:
                        self.filename = image_file
                        self.load_file(self.filename)
                        batch = False

            if (model_type in _BATCH_PROCESSING_VIDEO_MODELS) and (batch_processing_mode != "video"):
                self.filename = image_file
                self.load_file(self.filename)
                batch = False

            roi = getattr(self, "_batch_roi", None)

            if self.text_prompt:
                auto_labeling_result = self.auto_labeling_widget.model_manager.predict_shapes(
                    self.image, image_file, text_prompt=self.text_prompt, batch=batch, roi=roi
                )
            elif self.run_tracker:
                auto_labeling_result = self.auto_labeling_widget.model_manager.predict_shapes(
                    self.image, image_file, run_tracker=self.run_tracker, batch=batch, roi=roi
                )
                if batch_processing_mode == "video":
                    self.image_index = end_i + 1
                    break
            else:
                auto_labeling_result = self.auto_labeling_widget.model_manager.predict_shapes(
                    self.image, image_file, batch=batch, roi=roi
                )

            if batch:
                save_auto_labeling_result(self, image_file, auto_labeling_result)

            # ✅ 进度条按范围计数
            progress_dialog.setValue(self.image_index - start_i)

            self.image_index += 1

        finish_processing(self, progress_dialog)

    except Exception as e:
        progress_dialog.close()
        logger.error(f"Error occurred while processing images: {e}")
        popup = Popup(
            self.tr("Error occurred while processing images!"),
            self,
            icon=new_icon_path("error", "svg"),
        )
        popup.show_popup(self, position="center")


def show_progress_dialog_and_process(self):
    self.cancel_processing = False

    start_i = int(getattr(self, "_batch_start_index", 0))
    end_i = int(getattr(self, "_batch_end_index", len(self.image_list) - 1))
    total = max(0, end_i - start_i + 1)

    progress_dialog = QProgressDialog(
        self.tr("Processing..."),
        self.tr("Cancel"),
        0,
        max(0, total - 1),
        self,
    )
    progress_dialog.setWindowModality(Qt.WindowModal)
    progress_dialog.setWindowTitle(self.tr("Batch Processing"))
    progress_dialog.setMinimumWidth(400)
    progress_dialog.setMinimumHeight(150)

    initial_progress = (
        self.image_index + 1
        if self.image_index < len(self.image_list)
        else len(self.image_list)
    )
    progress_dialog.setValue(initial_progress)
    progress_dialog.setLabelText(
        f"Progress: {initial_progress}/{len(self.image_list)}"
    )
    progress_bar = progress_dialog.findChild(QtWidgets.QProgressBar)

    if progress_bar:
        model_type = (
            self.auto_labeling_widget.model_manager.loaded_model_config.get("type", "")
        )
        batch_processing_mode = "default"
        if model_type == "remote_server":
            model = self.auto_labeling_widget.model_manager.loaded_model_config.get(
                "model"
            )
            batch_processing_mode = model.get_batch_processing_mode()

        def update_progress(value):
            if batch_processing_mode != "video":
                progress_dialog.setLabelText(f"{value + 1}/{total}")

        progress_bar.valueChanged.connect(update_progress)

    progress_dialog.setStyleSheet(
        """
        QProgressDialog {
            background-color: rgba(255, 255, 255, 0.95);
            border-radius: 12px;
            min-width: 280px;
            min-height: 120px;
            padding: 20px;
            backdrop-filter: blur(20px);
            box-shadow: 0 10px 20px rgba(0, 0, 0, 0.08),
                        0 2px 6px rgba(0, 0, 0, 0.04);
        }
        QProgressBar {
            border: none;
            border-radius: 4px;
            background-color: rgba(0, 0, 0, 0.05);
            text-align: center;
            color: #1d1d1f;
            font-size: 13px;
            min-height: 20px;
            max-height: 20px;
            margin: 16px 0;
        }
        QProgressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #0066FF,
                stop:0.5 #00A6FF,
                stop:1 #0066FF);
            border-radius: 3px;
        }
        QLabel {
            color: #1d1d1f;
            font-size: 13px;
            font-weight: 500;
            margin-bottom: 8px;
        }
        QPushButton {
            background-color: rgba(255, 255, 255, 0.8);
            border: 0.5px solid rgba(0, 0, 0, 0.1);
            border-radius: 6px;
            font-weight: 500;
            font-size: 13px;
            color: #0066FF;
            min-width: 82px;
            height: 36px;
            padding: 0 16px;
            margin-top: 16px;
        }
        QPushButton:hover {
            background-color: rgba(0, 0, 0, 0.05);
        }
        QPushButton:pressed {
            background-color: rgba(0, 0, 0, 0.08);
        }
    """
    )
    progress_dialog.canceled.connect(lambda: cancel_operation(self))
    progress_dialog.show()

    QTimer.singleShot(200, lambda: process_next_image(self, progress_dialog))

def run_all_images(self):
    if len(self.image_list) < 1:
        return

    if self.auto_labeling_widget.model_manager.loaded_model_config is None:
        self.auto_labeling_widget.model_manager.new_model_status.emit(
            self.tr("Model is not loaded. Choose a mode to continue.")
        )
        return

    # ✅ 先确认
    response = QtWidgets.QMessageBox()
    response.setIcon(QtWidgets.QMessageBox.Warning)
    response.setWindowTitle(self.tr("Confirmation"))
    response.setText(self.tr("Do you want to process images in batch?"))
    response.setStandardButtons(QtWidgets.QMessageBox.Cancel | QtWidgets.QMessageBox.Ok)
    response.setStyleSheet(get_msg_box_style())
    if response.exec_() != QtWidgets.QMessageBox.Ok:
        return

    # ✅ 新增：选择范围（默认：当前 -> 最后）
    if not hasattr(self, "fn_to_index") or self.filename is None:
        return
    current_index = self.fn_to_index.get(str(self.filename), 0)
    total_images = len(self.image_list)
    dlg = RangeSelectDialog(
        parent=self,
        total_images=total_images,
        default_start=current_index,
        default_end=total_images - 1,
    )
    start_i, end_i = dlg.get_range()
    if start_i is None or end_i is None:
        return

    self._batch_start_index = int(start_i)
    self._batch_end_index = int(end_i)

    # ROI（保持你现有逻辑）
    self._batch_roi = None
    try:
        roi_enabled = (
            hasattr(self, "auto_labeling_widget")
            and hasattr(self.auto_labeling_widget, "button_roi_auto_label")
            and self.auto_labeling_widget.button_roi_auto_label.isChecked()
        )
        if roi_enabled and hasattr(self, "get_roi_for_auto_labeling"):
            self._batch_roi = self.get_roi_for_auto_labeling()
            if self._batch_roi is None:
                self.auto_labeling_widget.model_manager.new_model_status.emit(
                    self.tr("区域自动标注已开启，但未设置ROI矩形框，无法批量运行。")
                )
                return
    except Exception:
        self._batch_roi = None

    if (
        self.auto_labeling_widget.model_manager.loaded_model_config["type"]
        in _BATCH_PROCESSING_INVALID_MODELS
    ):
        logger.warning(
            f"The model `{self.auto_labeling_widget.model_manager.loaded_model_config['type']}`"
            f" is not supported for this action."
            f" Please choose a valid model to execute."
        )
        self.auto_labeling_widget.model_manager.new_model_status.emit(
            self.tr("Invalid model type, please choose a valid model_type to run.")
        )
        return

    response = QtWidgets.QMessageBox()
    response.setIcon(QtWidgets.QMessageBox.Warning)
    response.setWindowTitle(self.tr("Confirmation"))
    response.setText(self.tr("Do you want to process all images?"))
    response.setStandardButtons(
        QtWidgets.QMessageBox.Cancel | QtWidgets.QMessageBox.Ok
    )
    response.setStyleSheet(get_msg_box_style())
    if response.exec_() != QtWidgets.QMessageBox.Ok:
        return

    logger.info("Start running all images...")

    self.current_index = self.fn_to_index[str(self.filename)]
    self.image_index = self.current_index
    self.text_prompt = ""
    self.run_tracker = False

    model_type = self.auto_labeling_widget.model_manager.loaded_model_config[
        "type"
    ]

    if model_type == "remote_server":
        batch_processing_mode = "default"
        model = self.auto_labeling_widget.model_manager.loaded_model_config[
            "model"
        ]
        if hasattr(model, "get_batch_processing_mode"):
            batch_processing_mode = model.get_batch_processing_mode()
        else:
            batch_processing_mode = "default"
        if batch_processing_mode is None:
            self.auto_labeling_widget.model_manager.new_model_status.emit(
                self.tr(
                    "Batch processing is not supported for the current task."
                )
            )
            return
        if batch_processing_mode == "video":
            self.run_tracker = True
            show_progress_dialog_and_process(self)
        elif batch_processing_mode == "text_prompt":
            text_input_dialog = TextInputDialog(parent=self)
            self.text_prompt = text_input_dialog.get_input_text()
            if self.text_prompt:
                show_progress_dialog_and_process(self)
        else:
            show_progress_dialog_and_process(self)
    elif model_type in _BATCH_PROCESSING_TEXT_PROMPT_MODELS:
        text_input_dialog = TextInputDialog(parent=self)
        self.text_prompt = text_input_dialog.get_input_text()
        if self.text_prompt or model_type == "yoloe":
            show_progress_dialog_and_process(self)
    elif model_type == "florence2":
        self.text_prompt = self.auto_labeling_widget.edit_text.text()
        show_progress_dialog_and_process(self)
    elif model_type in _BATCH_PROCESSING_VIDEO_MODELS:
        self.run_tracker = True
        show_progress_dialog_and_process(self)
    else:
        show_progress_dialog_and_process(self)