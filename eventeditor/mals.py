from pathlib import Path
import struct
import typing

import oead

from eventeditor import totk_zs


class MessageArchiveError(RuntimeError):
    pass


_TOTK_TAG_NAMES: typing.Dict[typing.Tuple[int, int], str] = {
    (0, 0): 'ruby',
    (0, 1): 'font',
    (0, 2): 'size',
    (0, 3): 'color',
    (0, 4): 'pageBreak',
    (1, 0): 'delay',
    (1, 3): 'playSound',
    (1, 4): 'icon',
    (2, 1): 'string1',
    (2, 2): 'number2',
    (2, 3): 'currentHorseName',
    (2, 4): 'selectedHorseName',
    (2, 7): 'cookingAdjective',
    (2, 8): 'cookingEffectCaption',
    (2, 9): 'number9',
    (2, 11): 'string11',
    (2, 12): 'string12',
    (2, 14): 'number14',
    (2, 15): 'number15',
    (2, 16): 'number16',
    (2, 18): 'number18',
    (2, 19): 'number19',
    (2, 20): 'number20',
    (2, 21): 'number21',
    (2, 22): 'number22',
    (2, 24): 'attachmentAdjective',
    (2, 25): 'equipmentBaseName',
    (2, 26): 'essenceAdjective',
    (2, 27): 'essenceBaseName',
    (2, 28): 'weaponName',
    (2, 29): 'playerName',
    (2, 30): 'questItemName',
    (2, 31): 'string31',
    (2, 32): 'string32',
    (2, 33): 'string33',
    (2, 35): 'yonaDynamicName',
    (2, 36): 'string36',
    (2, 37): 'recipeName',
    (3, 0): 'setEmotion',
    (3, 1): 'setItalicFont',
    (4, 0): 'setVoice',
    (5, 0): 'delay8',
    (5, 1): 'delay15',
    (5, 2): 'delay30',
    (7, 0): 'extendVerticalSpace',
    (15, 0): 'resetFontStyle',
    (201, 0): 'wordInfo',
    (201, 1): 'defArticle',
    (201, 2): 'indefArticle',
    (201, 3): 'uppercaseNextWord',
    (201, 4): 'lowercaseNextWord',
    (201, 5): 'gender',
    (201, 6): 'pluralCase',
    (201, 7): 'batchimObject',
    (201, 8): 'batchimDirection',
    (201, 9): 'nounCase',
    (201, 10): 'gender10',
}

_TOTK_ICON_NAMES: typing.Dict[int, str] = {
    0: 'LStickUp',
    1: 'LStickDown',
    2: 'LStickLeft',
    3: 'LStickRight',
    4: 'RStickUpDown',
    5: 'RStickRightLeft',
    6: 'DPadUp',
    7: 'DPadDown',
    8: 'DPadLeft',
    9: 'DPadRight',
    10: 'AButton0',
    11: 'AButton1',
    12: 'JumpButton0',
    13: 'YButton',
    14: 'ZLTrigger0',
    15: 'ZLTrigger1',
    16: 'SprintButton0',
    17: 'SprintButton1',
    18: 'SprintButton2',
    19: 'SprintButton3',
    20: 'SprintButton4',
    21: 'RBumper0',
    22: 'LBumper',
    23: 'PlusButton',
    24: 'MinusButton',
    25: 'RightArrow',
    26: 'LeftArrow',
    27: 'UpArrow',
    28: 'DownArrow',
    29: 'UpRightArrow',
    30: 'UpLeftArrow',
    31: 'DownLeftArrow',
    32: 'DownRightArrow',
    33: 'LStick',
    34: 'RStick',
    35: 'LStickLeftRight',
    36: 'NintendoSwitch',
    37: 'JumpButton1',
    38: 'XButton2',
    39: 'BButton',
    40: 'XButton1',
    41: 'PristineWeaponSparkle',
    42: 'RBumper1',
    43: 'DPadUpDown',
    44: 'RoyalCrest',
}

_TOTK_EMOTION_NAMES: typing.Dict[int, str] = {
    0: 'Normal_Face',
    1: 'Pleasure_Face',
    2: 'Anger_Face',
    3: 'Sorrow_Face',
    4: 'Surprise_Face',
    5: 'Thinking_Face',
    6: 'Serious_Face',
    7: 'Normal',
    8: 'Pleasure',
    9: 'Angry',
    10: 'Sorrow',
    11: 'Surprise',
    12: 'Thinking',
    13: 'Serious',
}

_TOTK_FONT_NAMES: typing.Dict[int, str] = {
    -1: 'Default',
    0: 'Ancient',
    1: 'Thin',
    2: 'ThinOutlined',
    3: 'Unknown',
    4: 'Normal',
    5: 'NormalOutlined',
    6: 'Bold',
    7: 'TitleDeco',
    8: 'Title',
}


def _format_tag_argument_value(value: typing.Any) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _build_named_tag(name: str, **kwargs: typing.Any) -> str:
    parts = [name]
    for key, value in kwargs.items():
        parts.append(f'{key}="{_format_tag_argument_value(value)}"')
    return '{{' + ' '.join(parts) + '}}'


def load_messages_for_ids(path: str, message_ids: typing.Iterable[str], show_tags: bool = True) -> typing.Dict[str, str]:
    archive_path = Path(path)
    if not archive_path.is_file():
        raise MessageArchiveError(f'Message archive not found: {archive_path}')

    needed = _group_message_ids_by_prefix(message_ids)
    if not needed:
        return {}

    data = archive_path.read_bytes()
    if totk_zs.is_compressed_path(str(archive_path)):
        data = totk_zs.decompress(str(archive_path), data)

    messages: typing.Dict[str, str] = {}
    for file_name, file_data in _iter_msbt_files(str(archive_path), data):
        matching_prefixes = _matching_prefixes(file_name, needed.keys())
        if not matching_prefixes:
            continue

        try:
            parsed_messages = _parse_msbt(file_data, show_tags=show_tags)
        except MessageArchiveError:
            continue
        if not parsed_messages:
            continue

        for prefix in matching_prefixes:
            for label in needed[prefix]:
                text = parsed_messages.get(label)
                if text is not None:
                    messages[f'{prefix}:{label}'] = text

    return messages


def _group_message_ids_by_prefix(message_ids: typing.Iterable[str]) -> typing.Dict[str, typing.Set[str]]:
    grouped: typing.Dict[str, typing.Set[str]] = {}
    for message_id in message_ids:
        if not message_id or ':' not in message_id:
            continue
        prefix, label = message_id.split(':', 1)
        if not prefix or not label:
            continue
        grouped.setdefault(prefix, set()).add(label)
    return grouped


def _iter_msbt_files(path: str, data: bytes) -> typing.Iterable[typing.Tuple[str, bytes]]:
    lower_path = path.lower()
    if lower_path.endswith('.msbt'):
        yield Path(path).name, data
        return

    try:
        archive = oead.Sarc(data)
    except Exception as exc:
        raise MessageArchiveError(f'Unsupported message archive format: {path}') from exc

    for file in archive.get_files():
        if file.name.lower().endswith('.msbt'):
            yield file.name, bytes(file.data)


def _matching_prefixes(file_name: str, prefixes: typing.Iterable[str]) -> typing.List[str]:
    aliases = _candidate_prefix_aliases(file_name)
    return [prefix for prefix in prefixes if prefix in aliases]


def _candidate_prefix_aliases(file_name: str) -> typing.Set[str]:
    normalized = file_name.replace('\\', '/')
    if '.' in normalized:
        normalized = normalized.rsplit('.', 1)[0]

    parts = [part for part in normalized.split('/') if part]
    aliases = {normalized, Path(normalized).name}
    for idx in range(len(parts)):
        aliases.add('/'.join(parts[idx:]))
    return {alias for alias in aliases if alias}


def _parse_msbt(data: bytes, show_tags: bool = True) -> typing.Dict[str, str]:
    if len(data) < 0x20 or data[:8] != b'MsgStdBn':
        raise MessageArchiveError('Unsupported MSBT file header')

    endian = _determine_endian(data[8:10])
    encoding = _determine_encoding(data[0x0C], endian)
    section_count = struct.unpack_from(endian + 'H', data, 0x0E)[0]

    sections: typing.Dict[str, bytes] = {}
    offset = 0x20
    for _ in range(section_count):
        if offset + 0x10 > len(data):
            break
        section_name = data[offset:offset+4].decode('ascii', errors='ignore')
        section_size = struct.unpack_from(endian + 'I', data, offset + 4)[0]
        start = offset + 0x10
        end = start + section_size
        sections[section_name] = data[start:end]
        offset = _align(end, 0x10)

    labels = _parse_lbl1(sections.get('LBL1', b''), endian)
    texts = _parse_txt2(sections.get('TXT2', b''), endian, encoding, show_tags=show_tags)

    messages: typing.Dict[str, str] = {}
    for index, label in labels.items():
        if 0 <= index < len(texts):
            messages[label] = texts[index]
    return messages


def _determine_endian(bom: bytes) -> str:
    if bom == b'\xff\xfe':
        return '<'
    if bom == b'\xfe\xff':
        return '>'
    raise MessageArchiveError('Unsupported MSBT BOM')


def _determine_encoding(value: int, endian: str) -> str:
    if value == 0:
        return 'utf-8'
    if value == 1:
        return 'utf-16-le' if endian == '<' else 'utf-16-be'
    if value == 2:
        return 'utf-32-le' if endian == '<' else 'utf-32-be'
    return 'utf-16-le' if endian == '<' else 'utf-16-be'


def _parse_lbl1(section: bytes, endian: str) -> typing.Dict[int, str]:
    if len(section) < 4:
        return {}

    group_count = struct.unpack_from(endian + 'I', section, 0)[0]
    table_end = 4 + group_count * 8
    if len(section) < table_end:
        return {}

    groups = []
    offset = 4
    for _ in range(group_count):
        label_count, label_offset = struct.unpack_from(endian + 'II', section, offset)
        groups.append((label_count, label_offset))
        offset += 8

    labels = _parse_lbl1_from_base(section, groups, 0, endian)
    if labels:
        return labels
    labels = _parse_lbl1_from_base(section, groups, table_end, endian)
    if labels:
        return labels
    return _parse_lbl1_from_base(section, groups, 4, endian)


def _parse_lbl1_from_base(section: bytes, groups: typing.Iterable[typing.Tuple[int, int]], base: int,
                          endian: str) -> typing.Dict[int, str]:
    labels: typing.Dict[int, str] = {}
    for label_count, label_offset in groups:
        offset = base + label_offset
        if offset < 0 or offset >= len(section):
            return {}
        for _ in range(label_count):
            if offset >= len(section):
                return {}
            label_length = section[offset]
            offset += 1
            if offset + label_length + 4 > len(section):
                return {}
            label = section[offset:offset + label_length].decode('utf-8', errors='ignore')
            offset += label_length
            index = struct.unpack_from(endian + 'I', section, offset)[0]
            offset += 4
            labels[index] = label
    return labels


def _parse_txt2(section: bytes, endian: str, encoding: str, show_tags: bool = True) -> typing.List[str]:
    if len(section) < 4:
        return []

    text_count = struct.unpack_from(endian + 'I', section, 0)[0]
    header_end = 4 + text_count * 4
    if len(section) < header_end:
        return []

    offsets = [
        struct.unpack_from(endian + 'I', section, 4 + i * 4)[0]
        for i in range(text_count)
    ]

    texts = _parse_txt2_from_base(section, offsets, 0, encoding, endian, show_tags=show_tags)
    if texts:
        return texts
    texts = _parse_txt2_from_base(section, offsets, header_end, encoding, endian, show_tags=show_tags)
    if texts:
        return texts
    return _parse_txt2_from_base(section, offsets, 4, encoding, endian, show_tags=show_tags)


def _parse_txt2_from_base(section: bytes, offsets: typing.List[int], base: int,
                          encoding: str, endian: str, show_tags: bool = True) -> typing.List[str]:
    texts: typing.List[str] = []
    for idx, start_offset in enumerate(offsets):
        start = base + start_offset
        end = len(section) if idx + 1 >= len(offsets) else base + offsets[idx + 1]
        if start < 0 or start > len(section) or end < start or end > len(section):
            return []
        texts.append(_decode_msbt_text(section[start:end], encoding, endian, show_tags=show_tags))
    return texts


def _decode_msbt_text(data: bytes, encoding: str, endian: str, show_tags: bool = True) -> str:
    if encoding.startswith('utf-16'):
        return _decode_utf16_msbt_text(data, endian, show_tags=show_tags)
    if encoding.startswith('utf-32'):
        decoded = data.decode(encoding, errors='ignore')
        return decoded.split('\x00', 1)[0].replace('\r\n', '\n')
    decoded = data.split(b'\x00', 1)[0].decode(encoding, errors='ignore')
    return decoded.replace('\r\n', '\n')


def _decode_utf16_msbt_text(data: bytes, endian: str, show_tags: bool = True) -> str:
    chars: typing.List[str] = []
    offset = 0
    while offset + 2 <= len(data):
        codepoint = struct.unpack_from(endian + 'H', data, offset)[0]
        offset += 2
        if codepoint == 0x0000:
            break
        if codepoint == 0x000E:
            if offset + 6 > len(data):
                break
            group = struct.unpack_from(endian + 'H', data, offset)[0]
            tag_type = struct.unpack_from(endian + 'H', data, offset + 2)[0]
            payload_size = struct.unpack_from(endian + 'H', data, offset + 4)[0]
            payload_start = offset + 6
            payload_end = payload_start + payload_size
            if payload_end > len(data):
                break
            if show_tags:
                chars.append(_format_msbt_tag(group, tag_type, data[payload_start:payload_end], endian))
            offset = payload_end
            continue
        chars.append(chr(codepoint))
    return ''.join(chars).replace('\r\n', '\n')


def _format_msbt_tag(group: int, tag_type: int, payload: bytes, endian: str) -> str:
    if (group, tag_type) == (1, 4) and payload:
        icon_id = payload[0]
        icon_name = _TOTK_ICON_NAMES.get(icon_id, f'Icon{icon_id}')
        return _build_named_tag('icon', type=icon_name)

    if (group, tag_type) == (0, 1) and len(payload) >= 2:
        font_id = struct.unpack_from(endian + 'h', payload, 0)[0]
        font_name = _TOTK_FONT_NAMES.get(font_id, str(font_id))
        return _build_named_tag('font', face=font_name)

    if (group, tag_type) == (0, 3) and len(payload) >= 2:
        color_id = struct.unpack_from(endian + 'h', payload, 0)[0]
        return _build_named_tag('color', id=color_id)

    if (group, tag_type) == (0, 2) and len(payload) >= 2:
        size_value = struct.unpack_from(endian + 'H', payload, 0)[0]
        return _build_named_tag('size', value=size_value)

    if (group, tag_type) == (3, 0) and payload:
        emotion_id = payload[0]
        emotion_name = _TOTK_EMOTION_NAMES.get(emotion_id, str(emotion_id))
        no_voice = bool(payload[1]) if len(payload) >= 2 else False
        return _build_named_tag('setEmotion', emotion=emotion_name, noVoice=no_voice)

    if (group, tag_type) == (4, 0) and payload:
        try:
            payload_len = struct.unpack_from(endian + 'H', payload, 0)[0] if len(payload) >= 2 else 0
            string_data = payload[2:2 + payload_len] if payload_len and len(payload) >= 2 + payload_len else payload[2:]
            voice_name = string_data.decode('utf-16-le' if endian == '<' else 'utf-16-be', errors='ignore').rstrip('\x00')
        except Exception:
            voice_name = ''
        return _build_named_tag('setVoice', asset=voice_name) if voice_name else _build_named_tag('setVoice')

    if (group, tag_type) == (1, 0) and len(payload) >= 2:
        frame_count = struct.unpack_from(endian + 'H', payload, 0)[0]
        return _build_named_tag('delay', frames=frame_count)

    tag_name = _TOTK_TAG_NAMES.get((group, tag_type))
    if not tag_name:
        return _build_named_tag(f'tag:{group}:{tag_type}')

    if tag_name == 'pageBreak':
        return _build_named_tag('pageBreak')
    return _build_named_tag(tag_name)


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)
