import argparse
import io
import os
from pathlib import Path
import re
import signal
import sys
import traceback
import typing

import evfl
from evfl import EventFlow
from evfl.event import SubFlowEvent
import eventeditor.ai as ai
import eventeditor.actor_json as aj
import eventeditor.mals as mals
import eventeditor.totk_zs as totk_zs
from eventeditor.actor_view import ActorView
from eventeditor.event_view import EventView
from eventeditor.flow_data import FlowData, FlowDataChangeReason
from eventeditor.flowchart_view import FlowchartView
import eventeditor.util as util
import PyQt5.QtCore as qc # type: ignore
import PyQt5.QtGui as qg # type: ignore
import PyQt5.QtWidgets as q # type: ignore
from . import _version

APP_DISPLAY_NAME = 'TOTK EventEditor'
APP_INTERNAL_NAME = 'eventeditor'
GITHUB_REPOSITORY_SLUG = 'cargocult-mods/TOTK-event-editor'
GITHUB_REPOSITORY_URL = f'https://github.com/{GITHUB_REPOSITORY_SLUG}'
UPSTREAM_REPOSITORY_URL = 'https://github.com/zeldamods/event-editor'
RELEASE_VERSION_ASSET = 'assets/release_version.txt'

DARK_THEME_STYLESHEET = '''
QWidget {
    color: #f0f0f0;
    background-color: #3c3f41;
}
QDialog, QMessageBox, QInputDialog {
    background-color: #3c3f41;
}
QToolTip {
    color: #f0f0f0;
    background-color: #4a525e;
    border: 1px solid #626b77;
}
QMenuBar {
    background-color: #444b57;
    color: #f0f0f0;
}
QMenuBar::item:selected {
    background-color: #57606d;
}
QMenuBar::item:disabled {
    color: #8f969f;
}
QMenu {
    background-color: #444b57;
    color: #f0f0f0;
    border: 1px solid #626b77;
}
QMenu::item:disabled {
    color: #8f969f;
    background-color: transparent;
}
QMenu::item:selected {
    background-color: #57606d;
}
QMenu::separator {
    height: 1px;
    background: #626b77;
    margin: 4px 8px;
}
QMenu::right-arrow {
    image: url(%RIGHT_ARROW_ICON%);
    width: 12px;
    height: 12px;
}
QHeaderView::section {
    background-color: #4a525e;
    color: #f0f0f0;
    border: 1px solid #626b77;
    padding: 4px;
}
QHeaderView::up-arrow {
    image: url(%UP_ARROW_ICON%);
}
QHeaderView::down-arrow {
    image: url(%DOWN_ARROW_ICON%);
}
QTabWidget::pane {
    border: 1px solid #626b77;
    background-color: #3c3f41;
}
QTabBar::tab {
    background-color: #4a525e;
    color: #f0f0f0;
    border: 1px solid #626b77;
    padding: 4px 10px;
}
QTabBar::tab:selected {
    background-color: #565f6b;
}
QTabBar::tab:!selected {
    margin-top: 1px;
}
QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox, QListView, QTableView, QTreeView {
    color: #f0f0f0;
    background-color: #34383c;
    border: 1px solid #626b77;
    selection-background-color: #2a82da;
    selection-color: #ffffff;
}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {
    color: #969696;
    background-color: #45494d;
}
QComboBox {
    padding-right: 18px;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 18px;
    border-left: 1px solid #626b77;
    background-color: #4a525e;
}
QComboBox::down-arrow {
    image: url(%DOWN_ARROW_ICON%);
    width: 12px;
    height: 12px;
}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    background-color: #4a525e;
    border-left: 1px solid #626b77;
    width: 16px;
}
QAbstractSpinBox::up-arrow {
    image: url(%UP_ARROW_ICON%);
    width: 12px;
    height: 12px;
}
QAbstractSpinBox::down-arrow {
    image: url(%DOWN_ARROW_ICON%);
    width: 12px;
    height: 12px;
}
QComboBox QAbstractItemView {
    background-color: #34383c;
    color: #f0f0f0;
    selection-background-color: #2a82da;
    selection-color: #ffffff;
}
QPushButton, QToolButton {
    color: #f0f0f0;
    background-color: #3f454d;
    border: 1px solid #626b77;
    padding: 3px 8px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #4a525e;
}
QPushButton:pressed, QToolButton:pressed {
    background-color: #2a82da;
}
QPushButton:disabled, QToolButton:disabled {
    color: #969696;
    background-color: #45494d;
}
QCheckBox, QRadioButton, QLabel, QGroupBox {
    color: #f0f0f0;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px;
    height: 14px;
}
QCheckBox::indicator:unchecked, QRadioButton::indicator:unchecked {
    background-color: #34383c;
    border: 1px solid #626b77;
}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background-color: #2a82da;
    border: 1px solid #7bb5f0;
}
QCheckBox::indicator:checked {
    image: url(%CHECK_ICON%);
}
QTreeView::branch:closed:has-children {
    image: url(%RIGHT_ARROW_ICON%);
}
QTreeView::branch:open:has-children {
    image: url(%EXPAND_MORE_ICON%);
}
QGroupBox {
    border: 1px solid #626b77;
    margin-top: 8px;
    padding-top: 8px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QTableView QTableCornerButton::section {
    background-color: #4a525e;
    border: 1px solid #626b77;
}
QAbstractItemView {
    alternate-background-color: #3f4449;
    gridline-color: #626b77;
    outline: none;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #3c3f41;
    border: none;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #5d6671;
    border: none;
    min-height: 18px;
    min-width: 18px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #737d89;
}
QScrollBar:vertical {
    width: 10px;
    margin: 2px 2px 2px 0;
}
QScrollBar:horizontal {
    height: 10px;
    margin: 0 2px 2px 2px;
}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
    border: none;
}
QSplitter::handle {
    background-color: #4a525e;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
}
QStatusBar {
    background-color: #3c3f41;
}
QFrame[frameShape="4"], QFrame[frameShape="5"] {
    color: #626b77;
}
'''

FLOW_OPEN_FILTER = 'Flowchart (*.bfevfl *.bfevfl.zs *.bfevfl.zstd *.bfevfl.gz)'
FLOW_FILTER_SUFFIXES = {
    'Uncompressed flowchart .bfevfl (*)': '.bfevfl',
    'Compressed TotK flowchart .bfevfl.zs (*)': '.bfevfl.zs',
    'Compressed flowchart .bfevfl.zstd (*)': '.bfevfl.zstd',
    'Autosave .bfevfl.gz (*)': '.bfevfl.gz',
}
FLOW_SAVE_FILTER = ';;'.join(FLOW_FILTER_SUFFIXES.keys())
DEFAULT_FLOW_FILTER = 'Uncompressed flowchart .bfevfl (*)'
FLOW_SUFFIX_FILTERS = {suffix: name_filter for name_filter, suffix in FLOW_FILTER_SUFFIXES.items()}
SUPPORTED_FLOW_SUFFIXES = tuple(FLOW_FILTER_SUFFIXES.values())
SUPPORTED_FLOW_SUFFIXES_LONGEST_FIRST = tuple(sorted(SUPPORTED_FLOW_SUFFIXES, key=len, reverse=True))
SUPPORTED_DROP_SUFFIXES = ('.bfevfl', '.bfevfl.zs', '.bfevfl.zstd', '.bfevfl.gz')
EVENTFLOW_OPEN_SUFFIX_CANDIDATES = (
    '.bfevfl.zs',
    '.bfevfl.zstd',
    '.bfevfl.gz',
    '.bfevfl',
    '.evfl.zs',
    '.evfl.zstd',
    '.evfl.gz',
    '.evfl',
)
SUPPORTED_MALS_DROP_SUFFIXES = ('.sarc.zs', '.sarc', '.msbt')
FLOW_NAME_MATCH_SUFFIXES = SUPPORTED_FLOW_SUFFIXES + ('.evfl.zs', '.evfl.zstd', '.evfl.gz', '.evfl')
FLOW_NAME_MATCH_SUFFIXES_LONGEST_FIRST = tuple(sorted(FLOW_NAME_MATCH_SUFFIXES, key=len, reverse=True))
MALS_MODE_VANILLA = 'vanilla'
MALS_MODE_INFERRED = 'inferred'
MALS_MODE_MANUAL = 'manual'
MALS_MODES = (MALS_MODE_VANILLA, MALS_MODE_INFERRED, MALS_MODE_MANUAL)
DEFAULT_MALS_LOCALE = 'USen'
KNOWN_TOTK_MALS_LOCALES = (
    'CNzh',
    'EUde',
    'EUen',
    'EUes',
    'EUfr',
    'EUit',
    'EUnl',
    'EUru',
    'JPja',
    'KRko',
    'TWzh',
    'USen',
    'USes',
    'USfr',
)
MALS_ARCHIVE_SUFFIXES = ('.sarc.zs', '.sarc', '.msbt')
MALS_ARCHIVE_SUFFIXES_LONGEST_FIRST = tuple(sorted(MALS_ARCHIVE_SUFFIXES, key=len, reverse=True))
MALS_PRODUCT_SUFFIX_RE = re.compile(r'\.Product(?:\.[^.]+)*$', re.IGNORECASE)
MALS_LOCALE_NAME_RE = re.compile(r'^[A-Z]{2}[a-z]{2}$')
_STYLESHEET_ICON_CACHE: typing.Dict[typing.Tuple[str, str, str], str] = {}

def split_flow_path_suffix(path: str) -> typing.Tuple[str, str]:
    normalized_path = path.lower()
    for suffix in SUPPORTED_FLOW_SUFFIXES_LONGEST_FIRST:
        if normalized_path.endswith(suffix):
            return path[:-len(suffix)], suffix
    return path, ''

def strip_flow_path_suffixes(path: str) -> str:
    stripped_path = path
    while True:
        base_path, detected_suffix = split_flow_path_suffix(stripped_path)
        if not detected_suffix:
            return stripped_path
        stripped_path = base_path

def strip_flow_name_match_suffixes(path: str) -> str:
    stripped_path = path
    while True:
        lowered = stripped_path.lower()
        for suffix in FLOW_NAME_MATCH_SUFFIXES_LONGEST_FIRST:
            if lowered.endswith(suffix):
                stripped_path = stripped_path[:-len(suffix)]
                break
        else:
            return stripped_path

def normalize_flow_save_path(path: str, selected_filter: str) -> str:
    base = path
    while True:
        base, ext = os.path.splitext(base)
        if not ext:
            break

    if 'bfevfl.zs' in selected_filter:
        return base + '.bfevfl.zs'
    if 'bfevfl.zstd' in selected_filter:
        return base + '.bfevfl.zstd'
    if 'bfevfl.gz' in selected_filter:
        return base + '.bfevfl.gz'
    if 'bfevfl' in selected_filter:
        return base + '.bfevfl'
    return base

def iter_event_flow_flowcharts(flow: typing.Optional[EventFlow]) -> typing.Iterable[typing.Any]:
    if not flow:
        return

    seen: typing.Set[int] = set()

    def maybe_yield(flowchart) -> typing.Iterable[typing.Any]:
        if not flowchart:
            return
        object_id = id(flowchart)
        if object_id in seen:
            return
        seen.add(object_id)
        yield flowchart

    yield from maybe_yield(getattr(flow, 'flowchart', None))

    for attr_name in ('flowcharts', 'flow_charts'):
        collection = getattr(flow, attr_name, None)
        if not collection:
            continue
        if isinstance(collection, dict):
            values = collection.values()
        else:
            values = getattr(collection, 'data', collection)
        for item in values:
            yield from maybe_yield(getattr(item, 'v', item))

def flow_names_for_flow(flow: typing.Optional[EventFlow]) -> typing.List[str]:
    names: typing.List[str] = []

    def add_name(value) -> None:
        if isinstance(value, str) and value and value not in names:
            names.append(value)

    if flow:
        add_name(getattr(flow, 'name', ''))
    for flowchart in iter_event_flow_flowcharts(flow):
        add_name(getattr(flowchart, 'name', ''))
    return names

def primary_flow_name_for_flow(flow: typing.Optional[EventFlow]) -> str:
    if flow and getattr(flow, 'flowchart', None) and getattr(flow.flowchart, 'name', ''):
        return flow.flowchart.name
    names = flow_names_for_flow(flow)
    return names[0] if names else ''

def flow_filename_name_for_path(path: str) -> str:
    return Path(strip_flow_name_match_suffixes(Path(path).name)).name

def find_filename_flow_name_mismatch(path: str, flow: typing.Optional[EventFlow]) -> typing.Optional[typing.Tuple[str, typing.List[str]]]:
    filename = flow_filename_name_for_path(path)
    flow_names = flow_names_for_flow(flow)
    if not filename or not flow_names or filename in flow_names:
        return None
    return filename, flow_names

def find_missing_internal_subflow_calls(flow: typing.Optional[EventFlow]) -> typing.List[str]:
    if not flow:
        return []

    flowcharts = list(iter_event_flow_flowcharts(flow))
    entry_points_by_flow_name: typing.Dict[str, typing.Set[str]] = {}
    for flowchart in flowcharts:
        entry_names = {
            entry_point.name
            for entry_point in getattr(flowchart, 'entry_points', []) or []
            if getattr(entry_point, 'name', '')
        }
        for flow_name in {getattr(flow, 'name', ''), getattr(flowchart, 'name', '')}:
            if flow_name:
                entry_points_by_flow_name.setdefault(flow_name, set()).update(entry_names)

    missing: typing.List[str] = []
    known_flow_names = set(entry_points_by_flow_name.keys())
    for flowchart in flowcharts:
        source_flow_name = getattr(flowchart, 'name', '') or getattr(flow, 'name', '')
        for event in getattr(flowchart, 'events', []) or []:
            event_data = getattr(event, 'data', None)
            if not isinstance(event_data, SubFlowEvent):
                continue
            target_flow_name = event_data.res_flowchart_name or source_flow_name
            if event_data.res_flowchart_name and target_flow_name not in known_flow_names:
                continue
            target_entry_points = entry_points_by_flow_name.get(target_flow_name, set())
            if event_data.entry_point_name in target_entry_points:
                continue
            target_display = f'{target_flow_name}<{event_data.entry_point_name}>' if target_flow_name else f'<{event_data.entry_point_name}>'
            event_name = getattr(event, 'name', '<unnamed event>')
            missing.append(f'{event_name} calls {target_display}')
    return missing

def _path_from_parts(parts: typing.Sequence[str]) -> typing.Optional[Path]:
    if not parts:
        return None
    return Path(*parts)

def infer_eventflow_owner_root(flow_path: str) -> typing.Optional[Path]:
    if not flow_path:
        return None

    path = Path(flow_path)
    parts = path.parts
    lower_parts = [part.lower() for part in parts]
    for index in range(len(lower_parts) - 2):
        if lower_parts[index:index + 3] == ['romfs', 'event', 'eventflow']:
            return _path_from_parts(parts[:index])

    for index in range(len(lower_parts) - 1):
        if lower_parts[index:index + 2] == ['event', 'eventflow']:
            return _path_from_parts(parts[:index])
    return None

def infer_eventflow_mals_dir(flow_path: str) -> typing.Optional[Path]:
    owner_root = infer_eventflow_owner_root(flow_path)
    if not owner_root:
        return None

    parts = [part.lower() for part in Path(flow_path).parts]
    if 'romfs' in parts:
        return owner_root / 'romfs' / 'Mals'
    return owner_root / 'Mals'

def strip_mals_archive_suffix(path: str) -> str:
    stripped_path = Path(path).name
    lowered = stripped_path.lower()
    for suffix in MALS_ARCHIVE_SUFFIXES_LONGEST_FIRST:
        if lowered.endswith(suffix):
            return stripped_path[:-len(suffix)]
    return stripped_path

def mals_locale_name_for_path(path: typing.Union[str, Path]) -> str:
    base_name = strip_mals_archive_suffix(str(path))
    base_name = MALS_PRODUCT_SUFFIX_RE.sub('', base_name)
    return base_name

def is_mals_locale_name(value: typing.Any) -> bool:
    return isinstance(value, str) and bool(MALS_LOCALE_NAME_RE.match(value))

def discover_mals_locale_names(mals_dir: typing.Optional[Path]) -> typing.List[str]:
    if not mals_dir or not mals_dir.is_dir():
        return []

    locales: typing.Set[str] = set()
    for path in mals_dir.iterdir():
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if not any(lowered.endswith(suffix) for suffix in MALS_ARCHIVE_SUFFIXES):
            continue
        locale = mals_locale_name_for_path(path)
        if is_mals_locale_name(locale):
            locales.add(locale)
    return sorted(locales)

def _iter_mals_archives(mals_dir: Path) -> typing.Iterable[Path]:
    for path in mals_dir.iterdir():
        if not path.is_file():
            continue
        lowered = path.name.lower()
        if any(lowered.endswith(suffix) for suffix in MALS_ARCHIVE_SUFFIXES):
            yield path

def _mals_archive_sort_key(path: Path) -> typing.Tuple[int, int, str]:
    lowered = path.name.lower()
    suffix_priority = next(
        (index for index, suffix in enumerate(MALS_ARCHIVE_SUFFIXES_LONGEST_FIRST) if lowered.endswith(suffix)),
        len(MALS_ARCHIVE_SUFFIXES_LONGEST_FIRST),
    )
    product_priority = 0 if MALS_PRODUCT_SUFFIX_RE.search(strip_mals_archive_suffix(path.name)) else 1
    return suffix_priority, product_priority, lowered

def normalize_mals_locale(locale: str) -> str:
    return locale if is_mals_locale_name(locale) else DEFAULT_MALS_LOCALE

def choose_mals_archive_from_directory(mals_dir: typing.Optional[Path], locale: str = DEFAULT_MALS_LOCALE) -> str:
    if not mals_dir or not mals_dir.is_dir():
        return ''

    target_locale = normalize_mals_locale(locale)
    matches = [
        path
        for path in _iter_mals_archives(mals_dir)
        if mals_locale_name_for_path(path) == target_locale
    ]
    return str(sorted(matches, key=_mals_archive_sort_key)[0]) if matches else ''

def infer_mals_archive_for_flow_path(flow_path: str, locale: str = DEFAULT_MALS_LOCALE) -> str:
    return choose_mals_archive_from_directory(infer_eventflow_mals_dir(flow_path), locale)

def vanilla_mals_archive_path(locale: str = DEFAULT_MALS_LOCALE) -> str:
    romfs_path = totk_zs.get_romfs_path()
    if not romfs_path:
        return ''
    return choose_mals_archive_from_directory(Path(romfs_path) / 'Mals', locale)

def manual_mals_archive_path(manual_path: str, locale: str = DEFAULT_MALS_LOCALE) -> str:
    if not manual_path:
        return ''

    path = Path(manual_path)
    if path.is_dir():
        return choose_mals_archive_from_directory(path, locale)

    lowered = path.name.lower()
    if not any(lowered.endswith(suffix) for suffix in MALS_ARCHIVE_SUFFIXES):
        return ''
    if lowered.endswith('.msbt'):
        return str(path) if path.is_file() else ''
    if mals_locale_name_for_path(path) == normalize_mals_locale(locale):
        return str(path) if path.is_file() else ''
    return choose_mals_archive_from_directory(path.parent, locale)

def available_mals_locale_names(flow_path: str = '', manual_path: str = '') -> typing.List[str]:
    locales: typing.List[str] = []

    def add_many(values: typing.Iterable[str]) -> None:
        for value in values:
            if is_mals_locale_name(value) and value not in locales:
                locales.append(value)

    romfs_path = totk_zs.get_romfs_path()
    if romfs_path:
        add_many(discover_mals_locale_names(Path(romfs_path) / 'Mals'))

    add_many(discover_mals_locale_names(infer_eventflow_mals_dir(flow_path)))

    if manual_path:
        manual = Path(manual_path)
        if manual.is_dir():
            add_many(discover_mals_locale_names(manual))
        else:
            locale = mals_locale_name_for_path(manual)
            if is_mals_locale_name(locale):
                add_many([locale])
            add_many(discover_mals_locale_names(manual.parent))

    add_many(KNOWN_TOTK_MALS_LOCALES)
    return sorted(locales)

def is_path_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False

def is_vanilla_romfs_path(path: str) -> bool:
    romfs_path = totk_zs.get_romfs_path()
    if not path or not romfs_path:
        return False
    return is_path_relative_to(Path(path), Path(romfs_path))

def find_eventflow_file_in_directory(directory: typing.Optional[Path], flow_name: str) -> str:
    if not directory or not flow_name:
        return ''
    if not directory.is_dir():
        return ''

    direct_path = directory / flow_name
    if direct_path.is_file():
        return str(direct_path)

    stripped_name = flow_filename_name_for_path(flow_name)
    for suffix in EVENTFLOW_OPEN_SUFFIX_CANDIDATES:
        candidate = directory / f'{stripped_name}{suffix}'
        if candidate.is_file():
            return str(candidate)
    return ''

def current_mals_display_name(mode: str, current_path: str, flow_path: str, manual_path: str = '') -> str:
    if mode == MALS_MODE_VANILLA:
        return 'Vanilla'
    if mode == MALS_MODE_MANUAL:
        return 'Manual'

    romfs_path = totk_zs.get_romfs_path()
    if current_path and romfs_path and is_path_relative_to(Path(current_path), Path(romfs_path)):
        return 'Vanilla'

    if mode == MALS_MODE_INFERRED:
        owner_root = infer_eventflow_owner_root(flow_path)
        if owner_root:
            return owner_root.name or str(owner_root)
        return 'Inferred'
    return 'None'

def _tint_pixmap(pixmap: qg.QPixmap, color: qg.QColor) -> qg.QPixmap:
    tinted = qg.QPixmap(pixmap.size())
    tinted.fill(qc.Qt.transparent)
    painter = qg.QPainter(tinted)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(qg.QPainter.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return tinted

def _draw_arrow_primitive_icon_url(primitive_element: q.QStyle.PrimitiveElement, fallback_asset_name: str) -> str:
    app = q.QApplication.instance()
    if app:
        style = app.style()
        style_name = style.objectName() or style.metaObject().className()
        color_name = 'd6d9dd'
        cache_key = (style_name, f'primitive-{int(primitive_element)}', color_name)
        cached = _STYLESHEET_ICON_CACHE.get(cache_key)
        if cached:
            return cached

        pixmap = qg.QPixmap(24, 24)
        pixmap.fill(qc.Qt.transparent)
        painter = qg.QPainter(pixmap)
        option = q.QStyleOption()
        option.rect = qc.QRect(0, 0, 24, 24)
        option.palette = app.palette()
        style.drawPrimitive(primitive_element, option, painter, None)
        painter.end()
        if not pixmap.isNull():
            tinted = _tint_pixmap(pixmap, qg.QColor(f'#{color_name}'))
            cache_dir = Path(qc.QStandardPaths.writableLocation(qc.QStandardPaths.CacheLocation) or str(Path.cwd() / 'cache'))
            cache_dir = cache_dir / 'stylesheet-icons'
            cache_dir.mkdir(parents=True, exist_ok=True)
            icon_path = cache_dir / f'{style_name}_primitive_{int(primitive_element)}_{color_name}.png'
            tinted.save(str(icon_path), 'PNG')
            quoted_path = f'"{icon_path.resolve().as_posix()}"'
            _STYLESHEET_ICON_CACHE[cache_key] = quoted_path
            return quoted_path

    return f'"{Path(util.get_path(f"assets/{fallback_asset_name}")).resolve().as_posix()}"'

def build_dark_stylesheet() -> str:
    replacements = {
        '%DOWN_ARROW_ICON%': _draw_arrow_primitive_icon_url(q.QStyle.PE_IndicatorArrowDown, 'material_arrow_drop_down_24.svg'),
        '%UP_ARROW_ICON%': _draw_arrow_primitive_icon_url(q.QStyle.PE_IndicatorArrowUp, 'material_arrow_drop_up_24.svg'),
        '%RIGHT_ARROW_ICON%': _draw_arrow_primitive_icon_url(q.QStyle.PE_IndicatorArrowRight, 'material_chevron_right_24.svg'),
        '%EXPAND_MORE_ICON%': _draw_arrow_primitive_icon_url(q.QStyle.PE_IndicatorArrowDown, 'material_expand_more_24.svg'),
        '%CHECK_ICON%': f'"{Path(util.get_path("assets/material_check_18.svg")).resolve().as_posix()}"',
    }
    stylesheet = DARK_THEME_STYLESHEET
    for placeholder, value in replacements.items():
        stylesheet = stylesheet.replace(placeholder, value)
    return stylesheet

def serialize_flow_snapshot(flow: typing.Optional[EventFlow]) -> bytes:
    if not flow:
        return b''
    buffer = io.BytesIO()
    flow.write(buffer)
    return bytes(buffer.getvalue())

def deserialize_flow_snapshot(data: bytes) -> EventFlow:
    flow = EventFlow()
    flow.read(data)
    return flow

def describe_flow_change_reason(reason: FlowDataChangeReason) -> str:
    if reason & FlowDataChangeReason.EventFlowRename:
        return 'Rename flow'
    if reason & FlowDataChangeReason.EventParameters:
        return 'Edit event parameters'
    if reason & FlowDataChangeReason.Events:
        return 'Edit events'
    if reason & FlowDataChangeReason.Actors:
        return 'Edit actors'
    return 'Edit flow'

def normalize_display_version(version: typing.Optional[str]) -> str:
    if not version:
        return 'development build'
    version = str(version)
    if version in ('0+unknown', 'unknown', 'None') or version.startswith('0+unknown'):
        return 'development build'
    return version

def read_packaged_release_version() -> typing.Optional[str]:
    try:
        version = Path(util.get_path(RELEASE_VERSION_ASSET)).read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return None
    return version or None

def get_display_version() -> str:
    packaged_version = read_packaged_release_version()
    if packaged_version:
        return packaged_version
    return normalize_display_version(_version.get_versions().get('version'))

def build_about_html(version: str) -> str:
    return (
        f'<h2>{APP_DISPLAY_NAME}</h2>'
        '<p>A maintained EventEditor fork developed around Tears of the Kingdom modding workflows.</p>'
        f'<p><b>GitHub:</b> <a href="{GITHUB_REPOSITORY_URL}">{GITHUB_REPOSITORY_SLUG}</a></p>'
        f'<p><b>Upstream:</b> <a href="{UPSTREAM_REPOSITORY_URL}">zeldamods/event-editor</a></p>'
        '<p><small>'
        f'Version: {version}'
        '</small></p>'
    )

def set_application_display_name(display_name: str) -> None:
    setter = getattr(qc.QCoreApplication, 'setApplicationDisplayName', None)
    if callable(setter):
        setter(display_name)

class FlowUndoCommand(q.QUndoCommand):
    def __init__(self, window: 'MainWindow', before_snapshot: bytes, after_snapshot: bytes, text: str) -> None:
        super().__init__(text)
        self.window = window
        self.before_snapshot = before_snapshot
        self.after_snapshot = after_snapshot
        self._skip_initial_redo = True

    def undo(self) -> None:
        self.window.applyFlowHistorySnapshot(self.before_snapshot)

    def redo(self) -> None:
        if self._skip_initial_redo:
            self._skip_initial_redo = False
            return
        self.window.applyFlowHistorySnapshot(self.after_snapshot)

def build_dark_palette() -> qg.QPalette:
    palette = qg.QPalette()
    palette.setColor(qg.QPalette.Window, qg.QColor(60, 63, 65))
    palette.setColor(qg.QPalette.WindowText, qg.QColor(240, 240, 240))
    palette.setColor(qg.QPalette.Base, qg.QColor(52, 56, 60))
    palette.setColor(qg.QPalette.AlternateBase, qg.QColor(66, 70, 74))
    palette.setColor(qg.QPalette.Light, qg.QColor(80, 84, 88))
    palette.setColor(qg.QPalette.Midlight, qg.QColor(72, 76, 80))
    palette.setColor(qg.QPalette.Dark, qg.QColor(44, 47, 49))
    palette.setColor(qg.QPalette.Mid, qg.QColor(56, 60, 64))
    palette.setColor(qg.QPalette.Shadow, qg.QColor(20, 20, 20))
    palette.setColor(qg.QPalette.ToolTipBase, qg.QColor(74, 82, 94))
    palette.setColor(qg.QPalette.ToolTipText, qg.QColor(240, 240, 240))
    palette.setColor(qg.QPalette.Text, qg.QColor(240, 240, 240))
    palette.setColor(qg.QPalette.Button, qg.QColor(74, 78, 82))
    palette.setColor(qg.QPalette.ButtonText, qg.QColor(240, 240, 240))
    palette.setColor(qg.QPalette.BrightText, qg.QColor(255, 255, 255))
    palette.setColor(qg.QPalette.Highlight, qg.QColor(42, 130, 218))
    palette.setColor(qg.QPalette.HighlightedText, qg.QColor(255, 255, 255))
    palette.setColor(qg.QPalette.Link, qg.QColor(56, 152, 255))
    palette.setColor(qg.QPalette.LinkVisited, qg.QColor(110, 170, 255))
    try:
        palette.setColor(qg.QPalette.PlaceholderText, qg.QColor(185, 185, 185))
    except AttributeError:
        pass
    palette.setColor(qg.QPalette.Disabled, qg.QPalette.Text, qg.QColor(150, 150, 150))
    palette.setColor(qg.QPalette.Disabled, qg.QPalette.ButtonText, qg.QColor(150, 150, 150))
    palette.setColor(qg.QPalette.Disabled, qg.QPalette.WindowText, qg.QColor(150, 150, 150))
    palette.setColor(qg.QPalette.Disabled, qg.QPalette.Base, qg.QColor(69, 73, 77))
    palette.setColor(qg.QPalette.Disabled, qg.QPalette.Button, qg.QColor(69, 73, 77))
    return palette

class MainWindow(q.QMainWindow):
    def __init__(self, args) -> None:
        super().__init__()
        self.args = args
        self.flow: typing.Optional[EventFlow] = None
        self.flow_data = FlowData()
        self.flow_path = ''
        self.unsaved = False
        self.current_theme = 'light'
        self._syncing_flowchart_visibility = False
        self._restore_fullscreen = False
        self._restore_maximized = False
        self.undo_stack = q.QUndoStack(self)
        self.undo_stack.setUndoLimit(600)
        self._history_suspended = False
        self._history_snapshot = b''
        self._mals_mode = MALS_MODE_INFERRED
        self._mals_locale = DEFAULT_MALS_LOCALE
        self._manual_mals_path = ''
        self._include_mals_text_tags = True
        self._render_mals_tags_as_styling = True
        self._hide_non_formatting_mals_tags = False
        self._include_mals_blank_lines = False
        self._show_mals_text_bubble_breaks = True
        self._startup_entry_point_name = getattr(args, 'entry_point', '') or ''

        app = q.QApplication.instance()
        self.default_palette = qg.QPalette(app.palette()) if app else qg.QPalette()
        self.default_style_sheet = app.styleSheet() if app else ''

        self.initMenu()
        self.initWidgets()
        self.initLayout()

        self.connectWidgets()
        self.centralWidget().setHidden(True)
        self.updateTitleAndActions()

        self.readSettings()
        self._applyWindowIcon()
        self._initDragAndDrop()

        self.initVersionInfo()

    def initVersionInfo(self) -> None:
        self._version = get_display_version()

    def _applyWindowIcon(self) -> None:
        icon_path = util.get_icon_path()
        if not icon_path:
            return
        icon = qg.QIcon(icon_path)
        if icon.isNull():
            return
        self.setWindowIcon(icon)
        app = q.QApplication.instance()
        if app:
            app.setWindowIcon(icon)

    def _initDragAndDrop(self) -> None:
        self.setAcceptDrops(True)
        for widget in self.findChildren(q.QWidget):
            widget.setAcceptDrops(True)
        app = q.QApplication.instance()
        if app:
            app.installEventFilter(self)

    def _isSupportedFlowPath(self, path: str) -> bool:
        lower = path.lower()
        return lower.endswith(SUPPORTED_DROP_SUFFIXES)

    def _isSupportedMalsPath(self, path: str) -> bool:
        lower = path.lower()
        return lower.endswith(SUPPORTED_MALS_DROP_SUFFIXES)

    def _extractDroppedFlowPaths(self, event) -> typing.List[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []

        paths: typing.List[str] = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            if self._isSupportedFlowPath(local_path):
                paths.append(local_path)
        return paths

    def _extractDroppedMalsPaths(self, event) -> typing.List[str]:
        mime = event.mimeData()
        if not mime.hasUrls():
            return []

        paths: typing.List[str] = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            local_path = url.toLocalFile()
            if self._isSupportedMalsPath(local_path):
                paths.append(local_path)
        return paths

    def _launchNewInstanceForPath(self, path: str, entry_point_name: str = '') -> bool:
        launch_args: typing.List[str] = []
        if entry_point_name:
            launch_args.extend(['--entry-point', entry_point_name])
        launch_args.append(path)
        if getattr(sys, 'frozen', False):
            return qc.QProcess.startDetached(sys.executable, launch_args)
        return qc.QProcess.startDetached(sys.executable, ['-m', 'eventeditor'] + launch_args)

    def dragEnterEvent(self, event) -> None:
        if self._extractDroppedFlowPaths(event) or self._extractDroppedMalsPaths(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._extractDroppedFlowPaths(event) or self._extractDroppedMalsPaths(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        mals_paths = self._extractDroppedMalsPaths(event)
        if mals_paths:
            if self.setMalsPath(mals_paths[0], force_reload=True, report_errors=True, mode=MALS_MODE_MANUAL):
                event.acceptProposedAction()
                return
            event.ignore()
            return

        paths = self._extractDroppedFlowPaths(event)
        if not paths:
            event.ignore()
            return

        if self.flow:
            launched = True
            for path in paths:
                launched = self._launchNewInstanceForPath(path) and launched
            if launched:
                event.acceptProposedAction()
                return
            event.ignore()
            return

        opened = self.readFlow(paths[0])
        launched = True
        for path in paths[1:]:
            launched = self._launchNewInstanceForPath(path) and launched

        if opened and launched:
            event.acceptProposedAction()
            return
        event.ignore()

    def eventFilter(self, watched, event):
        event_type = event.type()
        if event_type in (qc.QEvent.DragEnter, qc.QEvent.DragMove, qc.QEvent.Drop):
            if not isinstance(watched, q.QWidget):
                return super().eventFilter(watched, event)
            if watched is not self and not self.isAncestorOf(watched):
                return super().eventFilter(watched, event)

            if event_type == qc.QEvent.DragEnter:
                self.dragEnterEvent(event)
            elif event_type == qc.QEvent.DragMove:
                self.dragMoveEvent(event)
            else:
                self.dropEvent(event)
            return event.isAccepted()
        return super().eventFilter(watched, event)

    def show(self) -> None:
        super().show()
        if self._restore_fullscreen:
            self.showFullScreen()
        elif self._restore_maximized:
            self.showMaximized()
        if self.args.event_flow_file:
            if self.readFlow(self.args.event_flow_file):
                self.selectStartupEntryPointIfRequested()

    def initMenu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu('&File')
        self.new_action = q.QAction('&New...', self)
        self.new_action.setShortcut(qg.QKeySequence.New)
        self.new_action.triggered.connect(self.onNewFile)
        file_menu.addAction(self.new_action)
        self.open_action = q.QAction('&Open...', self)
        self.open_action.setShortcut(qg.QKeySequence.Open)
        self.open_action.triggered.connect(self.onOpenFile)
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()
        self.open_autosave_action = q.QAction('Open autosave...', self)
        self.open_autosave_action.triggered.connect(lambda: self.onOpenFile(str(self.flow_data.auto_save.get_directory()), name_filter=f'Flowchart autosave (autosave_{self.flow_data.flow.name}_*.bfevfl.gz)'))
        if not self.flow_data.auto_save.get_directory():
            self.open_autosave_action.setVisible(False)
        file_menu.addAction(self.open_autosave_action)
        self.save_action = q.QAction('&Save', self)
        self.save_action.setShortcut(qg.QKeySequence.Save)
        self.save_action.setEnabled(False)
        self.save_action.triggered.connect(self.onSaveFile)
        file_menu.addAction(self.save_action)
        self.save_as_action = q.QAction('Save as...', self)
        # No shortcut is assigned for Windows in QKeySequence.SaveAs
        # self.save_as_action.setShortcut(qg.QKeySequence.SaveAs)
        self.save_as_action.setShortcut('Ctrl+Shift+S')
        self.save_as_action.setEnabled(False)
        self.save_as_action.triggered.connect(self.onSaveAsFile)
        file_menu.addAction(self.save_as_action)
        self.rename_flow_action = q.QAction('Rename flow', self)
        self.rename_flow_action.triggered.connect(self.renameFlow)
        file_menu.addAction(self.rename_flow_action)
        file_menu.addSeparator()
        self.exit_action = q.QAction('E&xit', self)
        self.exit_action.setShortcut(qg.QKeySequence.Quit)
        self.exit_action.triggered.connect(self.close)
        file_menu.addAction(self.exit_action)

        edit_menu = menu.addMenu('&Edit')
        self.undo_button_action = q.QAction('Undo', self)
        self.undo_button_action.setShortcut(qg.QKeySequence.Undo)
        self.undo_button_action.triggered.connect(self.undo_stack.undo)
        self.undo_button_action.setEnabled(False)
        edit_menu.addAction(self.undo_button_action)
        self.redo_button_action = q.QAction('Redo', self)
        self.redo_button_action.setShortcut(qg.QKeySequence.Redo)
        self.redo_button_action.triggered.connect(self.undo_stack.redo)
        self.redo_button_action.setEnabled(False)
        edit_menu.addAction(self.redo_button_action)

        view_menu = menu.addMenu('Flowc&hart')
        self.event_name_visible_action = q.QAction('Show &names', self)
        self.event_name_visible_action.setCheckable(True)
        self.event_name_visible_action.setChecked(False)
        self.event_name_visible_action.triggered.connect(self.onEventNameVisibilityChanged)
        view_menu.addAction(self.event_name_visible_action)
        self.event_param_visible_action = q.QAction('Show &parameters', self)
        self.event_param_visible_action.setCheckable(True)
        self.event_param_visible_action.setChecked(False)
        self.event_param_visible_action.triggered.connect(self.onEventParamVisibilityChanged)
        view_menu.addAction(self.event_param_visible_action)
        self.event_message_visible_action = q.QAction('Show message &text', self)
        self.event_message_visible_action.setCheckable(True)
        self.event_message_visible_action.setChecked(False)
        self.event_message_visible_action.triggered.connect(self.onEventMessageVisibilityChanged)
        view_menu.addAction(self.event_message_visible_action)
        view_menu.addSeparator()
        self.reload_graph_action = q.QAction('&Reload graph', self)
        self.reload_graph_action.setShortcut('Ctrl+Shift+R')
        view_menu.addAction(self.reload_graph_action)
        self.export_graph_action = q.QAction('E&xport graph data to JSON...', self)
        view_menu.addAction(self.export_graph_action)
        self.export_definitions_action = q.QAction('Ex&port actor definition data to JSON...', self)
        view_menu.addAction(self.export_definitions_action)
        self.reorder_event_parameters_action = q.QAction('Reorder event parameters', self)
        view_menu.addAction(self.reorder_event_parameters_action)
        view_menu.addSeparator()
        self.add_event_action = q.QAction('&Add event...', self)
        view_menu.addAction(self.add_event_action)
        self.add_fork_action = q.QAction('Add fork...', self)
        view_menu.addAction(self.add_fork_action)

        self.mals_menu = menu.addMenu('&Mals')
        self.current_mals_menu = q.QMenu('Current: None', self)
        self.open_mals_folder_action = q.QAction('Open Folder', self)
        self.open_mals_folder_action.triggered.connect(self.onOpenCurrentMalsFolder)
        self.current_mals_menu.addAction(self.open_mals_folder_action)
        self.open_current_mals_action = q.QAction('Open Mals', self)
        self.open_current_mals_action.triggered.connect(self.onOpenCurrentMals)
        self.current_mals_menu.addAction(self.open_current_mals_action)
        self.mals_menu.addMenu(self.current_mals_menu)
        self.mals_locale_menu = q.QMenu(f'Locale: {DEFAULT_MALS_LOCALE}', self)
        self._mals_locale_actions: typing.Dict[str, q.QAction] = {}
        self.mals_menu.addMenu(self.mals_locale_menu)
        self.mals_menu.addSeparator()

        self.vanilla_mals_action = q.QAction('Vanilla', self)
        self.vanilla_mals_action.triggered.connect(lambda: self.setMalsMode(MALS_MODE_VANILLA))
        self.mals_menu.addAction(self.vanilla_mals_action)
        self.inferred_mals_action = q.QAction('Inferred from EventFlow', self)
        self.inferred_mals_action.triggered.connect(lambda: self.setMalsMode(MALS_MODE_INFERRED))
        self.mals_menu.addAction(self.inferred_mals_action)
        self.manual_mals_action = q.QAction('Manual...', self)
        self.manual_mals_action.triggered.connect(self.onSetMalsPath)
        self.mals_menu.addAction(self.manual_mals_action)
        self.mals_menu.addSeparator()

        self.render_mals_tags_as_styling_action = q.QAction('Turn style tags into formatting', self)
        self.render_mals_tags_as_styling_action.setCheckable(True)
        self.render_mals_tags_as_styling_action.setChecked(True)
        self.render_mals_tags_as_styling_action.toggled.connect(self.onRenderMalsTagsAsStylingChanged)
        self.mals_menu.addAction(self.render_mals_tags_as_styling_action)
        self.hide_non_formatting_mals_tags_action = q.QAction('Hide non-formatting tags', self)
        self.hide_non_formatting_mals_tags_action.setCheckable(True)
        self.hide_non_formatting_mals_tags_action.setChecked(False)
        self.hide_non_formatting_mals_tags_action.toggled.connect(self.onHideNonFormattingMalsTagsChanged)
        self.mals_menu.addAction(self.hide_non_formatting_mals_tags_action)
        self.hide_mals_blank_lines_action = q.QAction('Hide blank lines', self)
        self.hide_mals_blank_lines_action.setCheckable(True)
        self.hide_mals_blank_lines_action.setChecked(True)
        self.hide_mals_blank_lines_action.toggled.connect(self.onHideMalsBlankLinesChanged)
        self.mals_menu.addAction(self.hide_mals_blank_lines_action)
        self.show_mals_text_bubble_breaks_action = q.QAction('Show text bubble breaks', self)
        self.show_mals_text_bubble_breaks_action.setCheckable(True)
        self.show_mals_text_bubble_breaks_action.setChecked(True)
        self.show_mals_text_bubble_breaks_action.toggled.connect(self.onShowMalsTextBubbleBreaksChanged)
        self.mals_menu.addAction(self.show_mals_text_bubble_breaks_action)
        self.mals_menu.addSeparator()

        self.mals_diagnostics_menu = q.QMenu('Diagnostics', self)
        self.show_missing_mals_report_action = q.QAction('Show Missing MSBT/Message IDs...', self)
        self.show_missing_mals_report_action.triggered.connect(self.onShowMissingMalsReport)
        self.mals_diagnostics_menu.addAction(self.show_missing_mals_report_action)
        self.mals_menu.addMenu(self.mals_diagnostics_menu)

        settings_menu = menu.addMenu('&Settings')
        self.set_totk_romfs_path_action = q.QAction('Set TOTK romfs path...', self)
        self.set_totk_romfs_path_action.triggered.connect(self.onSetTotkRomfsPath)
        settings_menu.addAction(self.set_totk_romfs_path_action)
        self.theme_toggle_action = q.QAction('', self)
        self.theme_toggle_action.triggered.connect(self.toggleTheme)
        settings_menu.addAction(self.theme_toggle_action)
        self.updateThemeToggleAction()

        help_menu = menu.addMenu('&Help')
        wiki_action = q.QAction('Wiki', self)
        wiki_action.triggered.connect(lambda: qg.QDesktopServices.openUrl(qc.QUrl('https://zeldamods.org')))
        help_menu.addAction(wiki_action)
        github_repo_action = q.QAction('GitHub repository', self)
        github_repo_action.triggered.connect(lambda: qg.QDesktopServices.openUrl(qc.QUrl(GITHUB_REPOSITORY_URL)))
        help_menu.addAction(github_repo_action)
        help_menu.addSeparator()
        about_action = q.QAction('About', self)
        about_action.triggered.connect(self.about)
        help_menu.addAction(about_action)

    def about(self) -> None:
        q.QMessageBox.about(self, f'About {APP_DISPLAY_NAME}', build_about_html(self._version))

    def initWidgets(self) -> None:
        self.tab_widget = q.QTabWidget(self)
        self.tab_widget.setTabPosition(q.QTabWidget.South)

        self.flowchart_view = FlowchartView(self, self.flow_data)
        self.actor_view = ActorView(self, self.flow_data)
        self.event_view = EventView(self, self.flow_data)

    def initLayout(self) -> None:
        self.tab_widget.addTab(self.flowchart_view, 'F&lowchart')
        self.tab_widget.addTab(self.actor_view, '&Actors')
        self.tab_widget.addTab(self.event_view, '&Events')

        self.setCentralWidget(self.tab_widget)

    def connectWidgets(self) -> None:
        self.flow_data.flowDataChanged.connect(self.recordUndoSnapshot)
        self.flow_data.flowDataChanged.connect(lambda reason: self.syncUndoState())
        self.undo_stack.indexChanged.connect(lambda _: self.syncUndoState())
        self.undo_stack.cleanChanged.connect(lambda _: self.syncUndoState())
        self.undo_stack.canUndoChanged.connect(self.undo_button_action.setEnabled)
        self.undo_stack.canRedoChanged.connect(self.redo_button_action.setEnabled)

        self.flowchart_view.readySignal.connect(self.onViewReady)
        self.flowchart_view.eventSelected.connect(self.onEventSelected)
        self.flowchart_view.externalSubflowOpenRequested.connect(self.onOpenExternalSubflowRequested)
        self.reload_graph_action.triggered.connect(self.flowchart_view.reload)
        self.export_graph_action.triggered.connect(self.flowchart_view.export)
        self.export_definitions_action.triggered.connect(self.flowchart_view.export_definitions)
        self.reorder_event_parameters_action.triggered.connect(self.flowchart_view.reorder_event_parameters)
        self.add_event_action.triggered.connect(self.flowchart_view.addNewEvent)
        self.add_fork_action.triggered.connect(self.flowchart_view.addFork)

        self.actor_view.detail_pane.jumpToEventsRequested.connect(self.onJumpToEventsRequested)
        self.actor_view.jumpToActorEventsRequested.connect(self.onJumpToEventsRequested)
        self.event_view.jumpToFlowchartRequested.connect(self.onJumpToFlowchartRequested)

        self.tab_widget.currentChanged.connect(self.onTabChanged)
        self.syncUndoState()

    def syncUndoState(self) -> None:
        self.unsaved = bool(self.flow) and not self.undo_stack.isClean()
        self.undo_button_action.setEnabled(bool(self.flow) and self.undo_stack.canUndo())
        self.redo_button_action.setEnabled(bool(self.flow) and self.undo_stack.canRedo())
        undo_text = self.undo_stack.undoText()
        redo_text = self.undo_stack.redoText()
        self.undo_button_action.setToolTip(undo_text if undo_text else 'Undo')
        self.redo_button_action.setToolTip(redo_text if redo_text else 'Redo')
        self.updateTitleAndActions()

    def resetUndoHistory(self) -> None:
        self._history_suspended = True
        self.undo_stack.clear()
        self._history_snapshot = serialize_flow_snapshot(self.flow)
        self.undo_stack.setClean()
        self._history_suspended = False
        self.syncUndoState()

    def recordUndoSnapshot(self, reason: FlowDataChangeReason) -> None:
        if self._history_suspended or not self.flow:
            return

        try:
            current_snapshot = serialize_flow_snapshot(self.flow)
        except Exception:
            traceback.print_exc()
            return
        if reason == FlowDataChangeReason.Reset:
            self._history_snapshot = current_snapshot
            return

        if not self._history_snapshot:
            self._history_snapshot = current_snapshot
            return

        if current_snapshot == self._history_snapshot:
            return

        self.undo_stack.push(
            FlowUndoCommand(
                self,
                self._history_snapshot,
                current_snapshot,
                describe_flow_change_reason(reason),
            )
        )
        self._history_snapshot = current_snapshot

    def applyFlowHistorySnapshot(self, snapshot: bytes) -> None:
        if not snapshot:
            return

        try:
            restored_flow = deserialize_flow_snapshot(snapshot)
        except Exception as exc:
            traceback.print_exc()
            q.QMessageBox.critical(self, 'Undo/Redo', f'Failed to restore flow history.\n\n{exc}')
            return

        self._history_suspended = True
        try:
            self.flowchart_view.web_object.preserveViewportRequested.emit()
            self.flowchart_view.suppress_reload_reselect = True
            self.flow = restored_flow
            self.flow_data.setFlow(restored_flow, emit_file_loaded=False)
            self.flowchart_view.selected_event = None
            self.flowchart_view.selected_node_id = None
            self.flowchart_view.pending_reveal_event = None
            self.flowchart_view.web_object.fileLoaded.emit(restored_flow)
            self._history_snapshot = snapshot
        finally:
            self._history_suspended = False

        self.syncUndoState()

    def closeEvent(self, event) -> None:
        if not self.unsaved or not self.flow:
            event.accept()
            self.writeSettings()
            return

        ret = q.QMessageBox.question(self, 'Unsaved changes', f'{self.flow.name} has unsaved changes. Save changes before closing?', q.QMessageBox.Yes | q.QMessageBox.No | q.QMessageBox.Cancel)

        if ret == q.QMessageBox.Yes:
            if not self.writeFlow(self.flow_path):
                event.ignore()
                return
            self.writeSettings()
            event.accept()
        elif ret == q.QMessageBox.No:
            self.writeSettings()
            event.accept()
        else:
            event.ignore()

    def readSettings(self) -> None:
        settings = qc.QSettings()
        totk_rom_root = settings.value('paths/totk_rom_root')
        ai.set_rom_path(totk_rom_root)
        totk_zs.set_romfs_path(totk_rom_root)
        aj.set_actor_definitions_path(settings.value('paths/actor_definitions_root'))
        settings.beginGroup('MainWindow')
        self.resize(settings.value('size', qc.QSize(800, 600)))
        self.move(settings.value('pos', qc.QPoint(200, 200)))
        self._restore_fullscreen = settings.value('fullscreen', False, type=bool)
        self._restore_maximized = settings.value('maximized', False, type=bool) and not self._restore_fullscreen
        settings.endGroup()

        settings.beginGroup('flowchart')
        self.event_name_visible_action.setChecked(settings.value('visible_names', False, type=bool))
        self.event_param_visible_action.setChecked(settings.value('visible_params', False, type=bool))
        self.event_message_visible_action.setChecked(settings.value('visible_messages', False, type=bool))
        settings.endGroup()

        settings.beginGroup('paths')
        legacy_mals_path = settings.value('mals_path', '')
        settings.endGroup()

        settings.beginGroup('mals')
        mode = settings.value('mode', '')
        manual_path = settings.value('manual_path', '')
        self._mals_locale = normalize_mals_locale(settings.value('locale', DEFAULT_MALS_LOCALE))
        self._render_mals_tags_as_styling = settings.value('render_tags_as_styling', True, type=bool)
        if settings.contains('hide_non_formatting_tags'):
            self._hide_non_formatting_mals_tags = settings.value('hide_non_formatting_tags', False, type=bool)
        else:
            self._hide_non_formatting_mals_tags = not settings.value('show_non_text_tags', True, type=bool)
        if settings.contains('hide_blank_lines'):
            self._include_mals_blank_lines = not settings.value('hide_blank_lines', True, type=bool)
        elif settings.contains('include_blank_lines'):
            self._include_mals_blank_lines = settings.value('include_blank_lines', False, type=bool)
        else:
            self._include_mals_blank_lines = False
        self._show_mals_text_bubble_breaks = settings.value('show_text_bubble_breaks', True, type=bool)
        settings.endGroup()

        if mode not in MALS_MODES:
            mode = MALS_MODE_MANUAL if legacy_mals_path else MALS_MODE_INFERRED
        self._mals_mode = mode
        self._manual_mals_path = manual_path or legacy_mals_path or ''
        self._include_mals_text_tags = True
        self.render_mals_tags_as_styling_action.setChecked(self._render_mals_tags_as_styling)
        self.hide_mals_blank_lines_action.setChecked(not self._include_mals_blank_lines)
        self.show_mals_text_bubble_breaks_action.setChecked(self._show_mals_text_bubble_breaks)
        self.hide_non_formatting_mals_tags_action.setChecked(self._hide_non_formatting_mals_tags)
        self.flowchart_view.eventTagVisibilityChanged.emit(self._include_mals_text_tags)
        self.flowchart_view.setMessageTagStylingEnabled(self._render_mals_tags_as_styling, refresh=False)
        self.flowchart_view.setNonTextMessageTagsVisible(not self._hide_non_formatting_mals_tags, refresh=False)
        self.flowchart_view.setMessageBlankLinesIncluded(self._include_mals_blank_lines, refresh=False)
        self.flowchart_view.setMessageBubbleBreaksShown(self._show_mals_text_bubble_breaks, refresh=False)
        self.applyMalsSelection(force_reload=False, report_errors=False)
        self.updateMalsPathActions()

        settings.beginGroup('appearance')
        self.applyTheme(settings.value('theme', 'light'), persist=False)
        settings.endGroup()

    def writeSettings(self) -> None:
        settings = qc.QSettings()
        settings.beginGroup('MainWindow')
        geometry = self.normalGeometry() if (self.isFullScreen() or self.isMaximized()) else self.geometry()
        settings.setValue('size', geometry.size())
        settings.setValue('pos', geometry.topLeft())
        settings.setValue('fullscreen', self.isFullScreen())
        settings.setValue('maximized', self.isMaximized())
        settings.endGroup()

        settings.beginGroup('flowchart')
        settings.setValue('visible_names', self.event_name_visible_action.isChecked())
        settings.setValue('visible_params', self.event_param_visible_action.isChecked())
        settings.setValue('visible_messages', self.event_message_visible_action.isChecked())
        settings.endGroup()

        settings.beginGroup('appearance')
        settings.setValue('theme', self.current_theme)
        settings.endGroup()

        settings.beginGroup('paths')
        if aj._actor_definitions_path:
            settings.setValue('actor_definitions_root', str(aj._actor_definitions_path))
        settings.setValue('mals_path', self.flowchart_view.getMessageArchivePath())
        settings.endGroup()

        settings.beginGroup('mals')
        settings.setValue('mode', self._mals_mode)
        settings.setValue('locale', self._mals_locale)
        settings.setValue('manual_path', self._manual_mals_path)
        settings.setValue('render_tags_as_styling', self._render_mals_tags_as_styling)
        settings.setValue('hide_non_formatting_tags', self._hide_non_formatting_mals_tags)
        settings.setValue('hide_blank_lines', not self._include_mals_blank_lines)
        settings.setValue('show_text_bubble_breaks', self._show_mals_text_bubble_breaks)
        settings.endGroup()

    def updateThemeToggleAction(self) -> None:
        self.theme_toggle_action.setText('Dark Mode' if self.current_theme == 'light' else 'Light Mode')

    def applyTheme(self, theme: str, persist: bool = True) -> None:
        if theme not in ('light', 'dark'):
            theme = 'light'

        app = q.QApplication.instance()
        if app:
            if theme == 'dark':
                app.setPalette(build_dark_palette())
                app.setStyleSheet(build_dark_stylesheet())
            else:
                app.setPalette(qg.QPalette(self.default_palette))
                app.setStyleSheet(self.default_style_sheet)

        self.current_theme = theme
        self.updateThemeToggleAction()
        self.flowchart_view.setDarkMode(theme == 'dark')

        if persist:
            settings = qc.QSettings()
            settings.beginGroup('appearance')
            settings.setValue('theme', theme)
            settings.endGroup()

    def toggleTheme(self) -> None:
        self.applyTheme('dark' if self.current_theme == 'light' else 'light')

    def updateMalsPathActions(self) -> None:
        current_path = self.flowchart_view.getMessageArchivePath()
        display_name = current_mals_display_name(
            self._mals_mode,
            current_path,
            self.flow_path,
            self._manual_mals_path,
        )
        self.current_mals_menu.setTitle(f'Current: {display_name}')
        self.updateMalsLocaleActions()

        for action, mode, label in (
            (self.vanilla_mals_action, MALS_MODE_VANILLA, 'Vanilla'),
            (self.inferred_mals_action, MALS_MODE_INFERRED, 'Inferred from EventFlow'),
            (self.manual_mals_action, MALS_MODE_MANUAL, 'Manual...'),
        ):
            action.setText(f'{"•" if self._mals_mode == mode else " "} {label}')

        has_path = bool(current_path)
        can_open_current = has_path and Path(current_path).exists()
        current_folder = self.currentMalsFolderPath()
        can_open_folder = bool(current_folder and Path(current_folder).exists())
        tooltip = current_path if has_path else 'No Mals/MSBT archive selected.'
        self.open_current_mals_action.setEnabled(can_open_current)
        self.open_current_mals_action.setToolTip(tooltip)
        self.open_mals_folder_action.setEnabled(can_open_folder)
        self.open_mals_folder_action.setToolTip(current_folder or tooltip)
        self.show_missing_mals_report_action.setEnabled(bool(self.flow))

    def updateMalsLocaleActions(self) -> None:
        self.mals_locale_menu.setTitle(f'Locale: {self._mals_locale}')
        locales = available_mals_locale_names(self.flow_path, self._manual_mals_path)
        if self._mals_locale not in locales:
            locales.append(self._mals_locale)
            locales.sort()

        if list(self._mals_locale_actions.keys()) != locales:
            self.mals_locale_menu.clear()
            self._mals_locale_actions = {}
            for locale in locales:
                action = q.QAction('', self)
                action.triggered.connect(lambda checked=False, locale=locale: self.setMalsLocale(locale))
                self.mals_locale_menu.addAction(action)
                self._mals_locale_actions[locale] = action

        for locale, action in self._mals_locale_actions.items():
            action.setText(f'{"•" if self._mals_locale == locale else " "} {locale}')

    def setMalsPath(self, path: str, force_reload: bool = True, report_errors: bool = True,
                    mode: typing.Optional[str] = None) -> bool:
        if not path:
            self.flowchart_view.clearMessageArchivePath(mals.mals_file_not_found_text(self._mals_locale))
            if mode in MALS_MODES:
                self._mals_mode = mode
            self.updateMalsPathActions()
            return True

        previous_path = self.flowchart_view.getMessageArchivePath()
        try:
            self.flowchart_view.setMessageArchivePath(path, force_reload=force_reload, report_errors=True)
        except totk_zs.MissingDictionaryPackError as exc:
            self.flowchart_view.setMessageArchivePath(previous_path, force_reload=False, report_errors=False)
            if self.promptForTotkRomfs(path):
                return self.setMalsPath(path, force_reload=force_reload, report_errors=report_errors)
            if report_errors:
                q.QMessageBox.critical(self, 'Mals path', f'Failed to load message archive.\n\n{exc}')
            return False
        except Exception as exc:
            self.flowchart_view.setMessageArchivePath(previous_path, force_reload=False, report_errors=False)
            if report_errors:
                traceback.print_exc()
                q.QMessageBox.critical(self, 'Mals path', f'Failed to load message archive.\n\n{exc}')
            return False

        if mode in MALS_MODES:
            self._mals_mode = mode
        if self._mals_mode == MALS_MODE_MANUAL:
            detected_locale = mals_locale_name_for_path(path)
            if is_mals_locale_name(detected_locale):
                self._mals_locale = detected_locale
        if self._mals_mode == MALS_MODE_MANUAL:
            self._manual_mals_path = path
        self.updateMalsPathActions()
        return True

    def setMalsMode(self, mode: str, force_reload: bool = True, report_errors: bool = True) -> bool:
        if mode not in MALS_MODES:
            return False

        previous_mode = self._mals_mode
        self._mals_mode = mode
        if self.applyMalsSelection(force_reload=force_reload, report_errors=report_errors):
            return True

        self._mals_mode = previous_mode
        self.applyMalsSelection(force_reload=False, report_errors=False)
        return False

    def setMalsLocale(self, locale: str, force_reload: bool = True, report_errors: bool = True) -> bool:
        locale = normalize_mals_locale(locale)
        if locale == self._mals_locale:
            self.updateMalsPathActions()
            return True

        self._mals_locale = locale
        self.applyMalsSelection(force_reload=force_reload, report_errors=report_errors)
        self.updateMalsPathActions()
        return True

    def applyMalsSelection(self, force_reload: bool = True, report_errors: bool = True) -> bool:
        if self._mals_mode == MALS_MODE_MANUAL:
            path = manual_mals_archive_path(self._manual_mals_path, self._mals_locale)
        elif self._mals_mode == MALS_MODE_VANILLA:
            path = vanilla_mals_archive_path(self._mals_locale)
        else:
            path = infer_mals_archive_for_flow_path(self.flow_path, self._mals_locale)

        if not path:
            self.flowchart_view.clearMessageArchivePath(mals.mals_file_not_found_text(self._mals_locale))
            self.updateMalsPathActions()
            if report_errors and self._mals_mode != MALS_MODE_MANUAL:
                source = 'vanilla RomFS' if self._mals_mode == MALS_MODE_VANILLA else 'current EventFlow path'
                q.QMessageBox.warning(
                    self,
                    'Mals path',
                    f'No {self._mals_locale} Mals archive could be found from the {source}.',
                )
            return True

        return self.setMalsPath(path, force_reload=force_reload, report_errors=report_errors)

    def onSetMalsPath(self) -> None:
        default_path = self._manual_mals_path or self.flowchart_view.getMessageArchivePath() or self.flow_path
        path = q.QFileDialog.getOpenFileName(
            self,
            'Select Mals/MSBT archive',
            default_path,
            'Message archives (*.sarc.zs *.sarc *.msbt);;All files (*)',
        )[0]
        if not path:
            self.updateMalsPathActions()
            return
        self.setMalsPath(path, force_reload=True, report_errors=True, mode=MALS_MODE_MANUAL)

    def onSetTotkRomfsPath(self) -> None:
        default_hint = self.flowchart_view.getMessageArchivePath() or self.flow_path
        if self.promptForTotkRomfs(default_hint) and self._mals_mode == MALS_MODE_VANILLA:
            self.applyMalsSelection(force_reload=True, report_errors=False)

    def onRenderMalsTagsAsStylingChanged(self, checked: bool) -> None:
        self._render_mals_tags_as_styling = bool(checked)
        self.flowchart_view.setMessageTagStylingEnabled(self._render_mals_tags_as_styling)

    def onHideNonFormattingMalsTagsChanged(self, checked: bool) -> None:
        self._hide_non_formatting_mals_tags = bool(checked)
        self.flowchart_view.setNonTextMessageTagsVisible(not self._hide_non_formatting_mals_tags)

    def onHideMalsBlankLinesChanged(self, checked: bool) -> None:
        self._include_mals_blank_lines = not bool(checked)
        self.flowchart_view.setMessageBlankLinesIncluded(self._include_mals_blank_lines)

    def onShowMalsTextBubbleBreaksChanged(self, checked: bool) -> None:
        self._show_mals_text_bubble_breaks = bool(checked)
        self.flowchart_view.setMessageBubbleBreaksShown(self._show_mals_text_bubble_breaks)

    def currentMalsFolderPath(self) -> str:
        current_path = self.flowchart_view.getMessageArchivePath()
        if self._mals_mode == MALS_MODE_INFERRED:
            owner_root = infer_eventflow_owner_root(self.flow_path)
            if owner_root and owner_root.exists():
                return str(owner_root)
        elif self._mals_mode == MALS_MODE_VANILLA:
            romfs_path = totk_zs.get_romfs_path()
            if romfs_path and Path(romfs_path).exists():
                return str(romfs_path)
        if current_path:
            return str(Path(current_path).parent)
        return ''

    def onOpenCurrentMalsFolder(self) -> None:
        folder = self.currentMalsFolderPath()
        if folder:
            qg.QDesktopServices.openUrl(qc.QUrl.fromLocalFile(folder))

    def onOpenCurrentMals(self) -> None:
        current_path = self.flowchart_view.getMessageArchivePath()
        if current_path:
            qg.QDesktopServices.openUrl(qc.QUrl.fromLocalFile(current_path))

    def onShowMissingMalsReport(self) -> None:
        report = self.flowchart_view.buildMessageLookupReport()
        dialog = q.QDialog(self, qc.Qt.WindowTitleHint | qc.Qt.WindowSystemMenuHint)
        dialog.setWindowTitle('Missing Mals references')
        dialog.resize(720, 480)
        layout = q.QVBoxLayout(dialog)
        editor = q.QPlainTextEdit(dialog)
        editor.setReadOnly(True)
        editor.setPlainText(report)
        layout.addWidget(editor)
        buttons = q.QDialogButtonBox(q.QDialogButtonBox.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()

    def currentModEventflowDirectories(self) -> typing.List[Path]:
        directories: typing.List[Path] = []
        if self.flow_path:
            directories.append(Path(self.flow_path).parent)

        owner_root = infer_eventflow_owner_root(self.flow_path)
        if owner_root:
            flow_parts = [part.lower() for part in Path(self.flow_path).parts]
            if 'romfs' in flow_parts:
                directories.append(owner_root / 'romfs' / 'Event' / 'EventFlow')
            directories.append(owner_root / 'Event' / 'EventFlow')

        unique_directories: typing.List[Path] = []
        seen: typing.Set[str] = set()
        for directory in directories:
            normalized = str(directory.resolve()) if directory.exists() else str(directory)
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_directories.append(directory)
        return unique_directories

    def findEventflowInCurrentMod(self, flow_name: str) -> str:
        for directory in self.currentModEventflowDirectories():
            path = find_eventflow_file_in_directory(directory, flow_name)
            if path:
                return path
        return ''

    def findEventflowInVanillaRomfs(self, flow_name: str) -> str:
        romfs_path = totk_zs.get_romfs_path()
        if not romfs_path:
            return ''
        return find_eventflow_file_in_directory(Path(romfs_path) / 'Event' / 'EventFlow', flow_name)

    def openSubflowTarget(self, path: str, entry_point_name: str) -> None:
        if not self._launchNewInstanceForPath(path, entry_point_name=entry_point_name):
            q.QMessageBox.warning(
                self,
                'Go to entry point',
                f'Failed to open {Path(path).name} in a new EventEditor window.',
            )

    def selectStartupEntryPointIfRequested(self) -> None:
        if not self._startup_entry_point_name or not self.flow:
            return
        entry_point_name = self._startup_entry_point_name
        self._startup_entry_point_name = ''
        self.tab_widget.setCurrentWidget(self.flowchart_view)
        self.flowchart_view.selectEntryPointByName(entry_point_name)

    def onOpenExternalSubflowRequested(self, flow_name: str, entry_point_name: str) -> None:
        display_name = f'{flow_name}<{entry_point_name}>'
        mod_path = self.findEventflowInCurrentMod(flow_name)
        if mod_path:
            ret = q.QMessageBox.question(
                self,
                'Go to entry point',
                f'{display_name} is an external subflow.\n\nOpen it from this mod folder?',
                q.QMessageBox.Open | q.QMessageBox.Cancel,
                q.QMessageBox.Cancel,
            )
            if ret == q.QMessageBox.Open:
                self.openSubflowTarget(mod_path, entry_point_name)
            return

        vanilla_path = self.findEventflowInVanillaRomfs(flow_name)
        if vanilla_path:
            ret = q.QMessageBox.question(
                self,
                'Go to entry point',
                f'{display_name} not found in mod.\n\nOpen vanilla?',
                q.QMessageBox.Open | q.QMessageBox.Cancel,
                q.QMessageBox.Cancel,
            )
            if ret == q.QMessageBox.Open:
                self.openSubflowTarget(vanilla_path, entry_point_name)
            return

        q.QMessageBox.information(
            self,
            'Go to entry point',
            f'{display_name} not found in mod or vanilla.',
        )

    def promptForTotkRomfs(self, path: str) -> bool:
        base_dir = ''
        romfs_path = totk_zs.get_romfs_path()
        if romfs_path and romfs_path.is_dir():
            base_dir = str(romfs_path)
        elif path:
            base_dir = str(Path(path).parent)

        selected_dir = q.QFileDialog.getExistingDirectory(
            self,
            'Select TotK RomFS folder',
            base_dir,
        )
        if not selected_dir:
            return False

        romfs_root = Path(selected_dir)
        if romfs_root.name.lower() == 'pack' and (romfs_root / 'ZsDic.pack.zs').is_file():
            romfs_root = romfs_root.parent

        if not (romfs_root / 'Pack' / 'ZsDic.pack.zs').is_file():
            q.QMessageBox.warning(
                self,
                'TotK RomFS',
                'The selected folder is not a valid TotK RomFS root.\n\nIt must contain Pack/ZsDic.pack.zs.',
            )
            return False

        totk_zs.set_romfs_path(str(romfs_root))
        ai.set_rom_path(str(romfs_root))
        settings = qc.QSettings()
        settings.beginGroup('paths')
        settings.setValue('totk_rom_root', str(romfs_root))
        settings.endGroup()
        return True

    def _getFlowSavePath(self, title: str, default_path: str = '') -> str:
        current_default_path = default_path
        while True:
            initial_filter = DEFAULT_FLOW_FILTER
            if current_default_path:
                _, detected_suffix = split_flow_path_suffix(current_default_path)
                if detected_suffix:
                    initial_filter = FLOW_SUFFIX_FILTERS.get(detected_suffix, DEFAULT_FLOW_FILTER)

            initial_path = ''
            if current_default_path:
                initial_path = str(Path(current_default_path).parent / Path(strip_flow_path_suffixes(current_default_path)).name)

            options = q.QFileDialog.Options()
            path, selected_filter = q.QFileDialog.getSaveFileName(
                self,
                title,
                initial_path,
                FLOW_SAVE_FILTER,
                initial_filter,
                options,
            )
            if not path:
                return ''

            normalized_path = normalize_flow_save_path(path, selected_filter or initial_filter)
            if not os.path.exists(normalized_path):
                return normalized_path

            message_box = q.QMessageBox(self)
            message_box.setIcon(q.QMessageBox.Warning)
            message_box.setWindowTitle('File Already Exists')
            message_box.setText(f'{Path(normalized_path).name} already exists.')
            message_box.setInformativeText('Do you want to replace it?')
            message_box.setStandardButtons(q.QMessageBox.Yes | q.QMessageBox.No)
            message_box.setDefaultButton(q.QMessageBox.No)
            if message_box.exec_() == q.QMessageBox.Yes:
                return normalized_path

            current_default_path = normalized_path

    def updateTitleAndActions(self) -> None:
        if not self.flow:
            self.setWindowTitle(APP_DISPLAY_NAME)
        else:
            indicator = '*' if self.unsaved else ''
            title_name = Path(self.flow_path).name if self.flow_path else primary_flow_name_for_flow(self.flow)
            self.setWindowTitle(f'{APP_DISPLAY_NAME} - {indicator}{title_name}')

        self.open_autosave_action.setEnabled(bool(self.flow) and bool(self.flow_path))
        self.save_action.setEnabled(bool(self.flow) and bool(self.flow_path))
        self.save_as_action.setEnabled(bool(self.flow))
        self.rename_flow_action.setEnabled(bool(self.flow) and bool(self.flow_path))

        self.reload_graph_action.setEnabled(bool(self.flow) and bool(self.flow_path))
        self.export_graph_action.setEnabled(bool(self.flow))
        self.export_definitions_action.setEnabled(bool(self.flow))
        self.reorder_event_parameters_action.setEnabled(bool(self.flow))
        self.add_event_action.setEnabled(bool(self.flow) and bool(self.flow_path))
        self.add_fork_action.setEnabled(bool(self.flow) and bool(self.flow_path))

    def renameFlow(self) -> None:
        if not self.flow or not self.flow.flowchart:
            return
        text, ok = q.QInputDialog.getText(self, 'Rename', 'Enter a new name for the flowchart.', q.QLineEdit.Normal, self.flow.name)
        if not ok or not text:
            return
        self.flow.name = text
        self.flow.flowchart.name = text
        self.flow_data.flowDataChanged.emit(FlowDataChangeReason.EventFlowRename)

    def confirmFilenameFlowNameMatchForSave(self, path: str) -> bool:
        mismatch = find_filename_flow_name_mismatch(path, self.flow)
        if not mismatch:
            return True

        filename, flow_names = mismatch
        ret = q.QMessageBox.warning(
            self,
            'Filename does not match flow name',
            'The filename does not match any named flow inside this file.\n\n'
            'In TOTK this will probably cause the EventFlow not to run.\n\n'
            f'Filename: {filename}\n'
            f'Flow names: {", ".join(flow_names) if flow_names else "(none)"}',
            q.QMessageBox.Ok | q.QMessageBox.Cancel,
            q.QMessageBox.Cancel,
        )
        return ret == q.QMessageBox.Ok

    def confirmInternalSubflowTargetsForSave(self) -> bool:
        missing_calls = find_missing_internal_subflow_calls(self.flow)
        if not missing_calls:
            return True

        listed_calls = '\n'.join(f'- {call}' for call in missing_calls[:50])
        if len(missing_calls) > 50:
            listed_calls += f'\n- ...and {len(missing_calls) - 50} more'
        ret = q.QMessageBox.warning(
            self,
            'Missing internal subflow entry points',
            'Some subflows call entry points inside this file that do not exist.\n\n'
            'In TOTK this may cause the EventFlow not to run.\n\n'
            f'{listed_calls}',
            q.QMessageBox.Ok | q.QMessageBox.Cancel,
            q.QMessageBox.Cancel,
        )
        return ret == q.QMessageBox.Ok

    def confirmSaveChecks(self, path: str) -> bool:
        return (
            self.confirmFilenameFlowNameMatchForSave(path) and
            self.confirmInternalSubflowTargetsForSave()
        )

    def confirmVanillaRomfsSaveTarget(self, path: str) -> str:
        if not is_vanilla_romfs_path(path):
            return 'save'

        message_box = q.QMessageBox(self)
        message_box.setIcon(q.QMessageBox.Warning)
        message_box.setWindowTitle('Save')
        message_box.setText('Warning: You are saving into the vanilla romfs dump.\nDid you really mean to?')
        cancel_button = message_box.addButton('Cancel', q.QMessageBox.RejectRole)
        yes_button = message_box.addButton('Yes', q.QMessageBox.AcceptRole)
        save_as_button = message_box.addButton('Save As', q.QMessageBox.ActionRole)
        message_box.setDefaultButton(cancel_button)
        message_box.exec_()

        clicked_button = message_box.clickedButton()
        if clicked_button == yes_button:
            return 'save'
        if clicked_button == save_as_button:
            return 'save_as'
        return 'cancel'

    def readFlow(self, path: str) -> bool:
        if self.flow and self.unsaved:
            ret = q.QMessageBox.question(self, 'Unsaved changes', f'{self.flow.name} has unsaved changes. Save changes before opening another file?', q.QMessageBox.Yes | q.QMessageBox.No | q.QMessageBox.Cancel)
            if ret == q.QMessageBox.Yes:
                if not self.writeFlow(self.flow_path):
                    return False
            elif ret == q.QMessageBox.Cancel:
                return False

        try:
            flow = EventFlow()
            util.read_flow(path, flow)
            self.flow = flow
            self.flow_path = path
            self.flow_data.setFlow(flow)
            self.resetUndoHistory()
            if self._mals_mode in (MALS_MODE_VANILLA, MALS_MODE_INFERRED):
                self.applyMalsSelection(force_reload=True, report_errors=False)
            else:
                self.updateMalsPathActions()
            return True
        except totk_zs.MissingDictionaryPackError as exc:
            if self.promptForTotkRomfs(path):
                return self.readFlow(path)
            q.QMessageBox.critical(self, 'Open', f'Failed to load event flow.\n\n{exc}')
            return False
        except Exception as exc:
            traceback.print_exc()
            q.QMessageBox.critical(self, 'Open', f'Failed to load event flow.\n\n{exc}')
            return False

    def writeFlow(self, path: str) -> bool:
        if not self.flow or not path:
            return False

        vanilla_save_choice = self.confirmVanillaRomfsSaveTarget(path)
        if vanilla_save_choice == 'cancel':
            return False
        if vanilla_save_choice == 'save_as':
            save_as_path = self._getFlowSavePath('Save as...', path)
            if not save_as_path:
                return False
            return self.writeFlow(save_as_path)

        if not self.confirmSaveChecks(path):
            return False

        try:
            util.write_flow(path, self.flow)
            self.flow_path = path
            self.undo_stack.setClean()
            if self._mals_mode == MALS_MODE_INFERRED:
                self.applyMalsSelection(force_reload=True, report_errors=False)
            else:
                self.updateMalsPathActions()
            self.syncUndoState()
            return True
        except totk_zs.MissingDictionaryPackError as exc:
            if self.promptForTotkRomfs(path):
                return self.writeFlow(path)
            q.QMessageBox.critical(self, 'Save', f'Failed to write event flow.\n\n{exc}')
            return False
        except Exception as exc:
            traceback.print_exc()
            q.QMessageBox.critical(self, 'Save', f'Failed to write event flow. Please ensure there are no placeholder events left.\n\n{exc}')
            return False

    def onNewFile(self) -> bool:
        path = self._getFlowSavePath('Select a location for the new file')
        if not path:
            return False
        flow = evfl.EventFlow()
        flow.name = 'NewFile'
        flow.flowchart = evfl.Flowchart()
        flow.flowchart.name = 'NewFile'
        try:
            util.write_flow(path, flow)
        except totk_zs.MissingDictionaryPackError as exc:
            if self.promptForTotkRomfs(path):
                try:
                    util.write_flow(path, flow)
                except Exception as retry_exc:
                    traceback.print_exc()
                    q.QMessageBox.critical(self, 'New file', f'Failed to write new event flow -- cannot continue\n\n{retry_exc}')
                    return False
            else:
                q.QMessageBox.critical(self, 'New file', f'Failed to write new event flow -- cannot continue\n\n{exc}')
                return False
        except Exception as exc:
            traceback.print_exc()
            q.QMessageBox.critical(self, 'New file', f'Failed to write new event flow -- cannot continue\n\n{exc}')
            return False
        return self.readFlow(path)

    def onOpenFile(self, default_directory='', name_filter=FLOW_OPEN_FILTER) -> bool:
        default_directory_ = default_directory if default_directory else self.flow_path
        path = q.QFileDialog.getOpenFileName(self, 'Open event flowchart', default_directory_, name_filter)[0]
        if path:
            return self.readFlow(path)
        return False

    def onSaveFile(self) -> None:
        self.writeFlow(self.flow_path)

    def onSaveAsFile(self) -> None:
        path = self._getFlowSavePath('Save as...', self.flow_path)
        self.writeFlow(path)

    def onTabChanged(self, idx: int) -> None:
        self.flowchart_view.setIsCurrentView(self.tab_widget.widget(idx) == self.flowchart_view)

    def onViewReady(self) -> None:
        self.centralWidget().setHidden(False)
        self._syncing_flowchart_visibility = True
        try:
            self.onEventNameVisibilityChanged()
            self.onEventParamVisibilityChanged()
            self.onEventMessageVisibilityChanged()
            self.onEventTagVisibilityChanged()
        finally:
            self._syncing_flowchart_visibility = False
        self.selectStartupEntryPointIfRequested()

    def onEventSelected(self, event_idx: int) -> None:
        self.event_view.selectEvent(event_idx)

    def onJumpToEventsRequested(self, filter_str: str = '') -> None:
        self.tab_widget.setCurrentWidget(self.event_view)
        if filter_str:
            self.event_view.search_bar.setValue(filter_str)
            self.event_view.search_bar.show()

    def onJumpToFlowchartRequested(self, idx: int) -> None:
        """Request a node select in the flowchart webview. Negative indices are used for entry points."""
        self.tab_widget.setCurrentWidget(self.flowchart_view)
        self.flowchart_view.selectRequested.emit(idx)

    def onEventNameVisibilityChanged(self) -> None:
        visible = self.event_name_visible_action.isChecked()
        self.flowchart_view.eventNameVisibilityChanged.emit(visible)
        if not self._syncing_flowchart_visibility:
            self.flowchart_view.refreshDisplayOptionsPreservingSelection()

    def onEventParamVisibilityChanged(self) -> None:
        visible = self.event_param_visible_action.isChecked()
        self.flowchart_view.eventParamVisibilityChanged.emit(visible)
        if not self._syncing_flowchart_visibility:
            self.flowchart_view.refreshDisplayOptionsPreservingSelection()

    def onEventMessageVisibilityChanged(self) -> None:
        visible = self.event_message_visible_action.isChecked()
        self.flowchart_view.eventMessageVisibilityChanged.emit(visible)
        if not self._syncing_flowchart_visibility:
            self.flowchart_view.refreshDisplayOptionsPreservingSelection()

    def onEventTagVisibilityChanged(self) -> None:
        self.flowchart_view.eventTagVisibilityChanged.emit(self._include_mals_text_tags)
        if not self._syncing_flowchart_visibility:
            self.flowchart_view.refreshDisplayOptionsPreservingSelection()

def main() -> None:
    qc.QCoreApplication.setOrganizationName('eventeditor')
    qc.QCoreApplication.setApplicationName(APP_INTERNAL_NAME)
    set_application_display_name(APP_DISPLAY_NAME)
    qc.QSettings.setDefaultFormat(qc.QSettings.IniFormat)

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    parser = argparse.ArgumentParser(prog='eventeditor', description=f'{APP_DISPLAY_NAME}: an event flow editor')
    parser.add_argument('--entry-point', default='', help='Entry point to select after opening the event flow file')
    parser.add_argument('event_flow_file', nargs='?', help='Event flow file to open')
    args, _ = parser.parse_known_args()
    app = q.QApplication(sys.argv)
    icon_path = util.get_icon_path()
    if icon_path:
        icon = qg.QIcon(icon_path)
        if not icon.isNull():
            app.setWindowIcon(icon)
    if os.name == 'nt':
        app_font = app.font()
        app_font.setFamily('Segoe UI')
        app_font.setPointSize(int(qg.QFontInfo(app_font).pointSize() * 1.20))
        app.setFont(app_font)
    win = MainWindow(args)
    win.show()
    ret = app.exec_()
    sys.exit(ret)

if __name__ == '__main__':
    main()
