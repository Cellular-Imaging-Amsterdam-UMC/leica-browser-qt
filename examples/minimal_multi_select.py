from PyQt6.QtWidgets import QApplication

from leica_browser_qt import LeicaBrowserDialog


app = QApplication([])
contexts = LeicaBrowserDialog.select_image_contexts()
for ctx in contexts:
    print(ctx.to_dict())
