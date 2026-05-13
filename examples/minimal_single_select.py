from PyQt6.QtWidgets import QApplication

from leica_browser_qt import LeicaBrowserDialog


app = QApplication([])
ctx = LeicaBrowserDialog.select_image_context()
if ctx is not None:
    print(ctx.to_dict())

