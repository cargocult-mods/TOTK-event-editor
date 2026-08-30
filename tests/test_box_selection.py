import os
import unittest
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_DISABLE_SANDBOX', '1')

from PyQt5 import QtCore as qc  # type: ignore
from PyQt5 import QtWidgets as q  # type: ignore
from PyQt5.QtWebEngineWidgets import QWebEngineView  # type: ignore


FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'box_selection_render.html'


class BoxSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = q.QApplication.instance() or q.QApplication([])

    def _wait_for_load(self, view: QWebEngineView) -> None:
        loop = qc.QEventLoop()
        result = {'loaded': False}

        def finish(loaded: bool) -> None:
            result['loaded'] = loaded
            loop.quit()

        view.loadFinished.connect(finish)
        view.load(qc.QUrl.fromLocalFile(str(FIXTURE)))
        qc.QTimer.singleShot(10000, loop.quit)
        loop.exec_()
        self.assertTrue(result['loaded'], 'box-selection fixture did not load')

    def _run_javascript(self, view: QWebEngineView, script: str):
        loop = qc.QEventLoop()
        result = {'value': None, 'called': False}

        def finish(value) -> None:
            result['value'] = value
            result['called'] = True
            loop.quit()

        view.page().runJavaScript(script, finish)
        qc.QTimer.singleShot(10000, loop.quit)
        loop.exec_()
        self.assertTrue(result['called'], 'box-selection JavaScript did not finish')
        return result['value']

    def test_shift_drag_selects_the_two_nodes_inside_the_marquee(self):
        view = QWebEngineView()
        self.addCleanup(view.close)
        view.resize(1000, 800)
        self._wait_for_load(view)

        selected_ids = self._run_javascript(view, 'window.runBoxSelectionTest();')

        self.assertEqual(selected_ids, [0, 1])

    def test_control_shift_drag_adds_nodes_to_the_existing_selection(self):
        view = QWebEngineView()
        self.addCleanup(view.close)
        view.resize(1000, 800)
        self._wait_for_load(view)

        selected_ids = self._run_javascript(view, 'window.runAdditiveBoxSelectionTest();')

        self.assertEqual(selected_ids, [0, 1, 2])

    def test_escape_cancels_the_marquee_and_restores_the_previous_selection(self):
        view = QWebEngineView()
        self.addCleanup(view.close)
        view.resize(1000, 800)
        self._wait_for_load(view)

        result = self._run_javascript(view, 'window.runCancelledBoxSelectionTest();')

        self.assertEqual(result['previewIds'], [0, 1])
        self.assertTrue(result['marqueeWasVisible'])
        self.assertEqual(result['selectedIds'], [2])
        self.assertTrue(result['marqueeIsHidden'])


if __name__ == '__main__':
    unittest.main()
