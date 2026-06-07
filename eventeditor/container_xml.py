import typing
import xml.etree.ElementTree as ET

from evfl import ActorIdentifier
from evfl.common import Argument


def _scalar_type_name(value: typing.Any) -> str:
    if isinstance(value, bool):
        return 'bool'
    if isinstance(value, int):
        return 'int'
    if isinstance(value, float):
        return 'float'
    if isinstance(value, str):
        if isinstance(value, Argument):
            return 'argument'
        return 'string'
    if isinstance(value, ActorIdentifier):
        return 'actor_identifier'
    raise ValueError(f'Unsupported container value type: {type(value).__name__}')


def _append_value(parent: ET.Element, key: str, value: typing.Any) -> None:
    item = ET.SubElement(parent, 'Item', {'key': key})
    if isinstance(value, list):
        item.set('type', 'list')
        element_type = _scalar_type_name(value[0]) if value else 'string'
        item.set('element_type', element_type)
        for entry in value:
            child = ET.SubElement(item, 'Value')
            _set_scalar_value(child, entry)
        return
    _set_scalar_value(item, value)


def _set_scalar_value(element: ET.Element, value: typing.Any) -> None:
    value_type = _scalar_type_name(value)
    element.set('type', value_type)
    if value_type == 'actor_identifier':
        element.set('name', value.name)
        element.set('sub_name', value.sub_name)
        return
    element.text = 'true' if value is True else 'false' if value is False else str(value)


def _parse_scalar(element: ET.Element, forced_type: typing.Optional[str] = None) -> typing.Any:
    value_type = forced_type or element.get('type', 'string')
    if value_type == 'bool':
        return (element.text or '').strip().lower() == 'true'
    if value_type == 'int':
        return int((element.text or '0').strip())
    if value_type == 'float':
        return float((element.text or '0').strip())
    if value_type == 'string':
        return element.text or ''
    if value_type == 'argument':
        return Argument(element.text or '')
    if value_type == 'actor_identifier':
        return ActorIdentifier(element.get('name', ''), element.get('sub_name', ''))
    raise ValueError(f'Unsupported XML value type: {value_type}')


def dumps_container_dict(data: typing.Dict[str, typing.Any]) -> str:
    root = ET.Element('Container')
    for key, value in data.items():
        _append_value(root, key, value)
    return ET.tostring(root, encoding='unicode')


def loads_container_dict(xml_text: str) -> typing.Dict[str, typing.Any]:
    root = ET.fromstring(xml_text)
    if root.tag != 'Container':
        raise ValueError('The XML root element must be <Container>.')

    result: typing.Dict[str, typing.Any] = {}
    for item in root.findall('Item'):
        key = item.get('key', '')
        if not key:
            raise ValueError('Every <Item> must have a non-empty key attribute.')
        if key in result:
            raise ValueError(f'Duplicate key in XML container: {key}')

        item_type = item.get('type', 'string')
        if item_type == 'list':
            element_type = item.get('element_type', 'string')
            values = [_parse_scalar(child, element_type) for child in item.findall('Value')]
            if not values:
                raise ValueError(f'List item "{key}" must contain at least one <Value>.')
            result[key] = values
        else:
            result[key] = _parse_scalar(item)
    return result
