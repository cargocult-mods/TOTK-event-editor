import typing
import xml.etree.ElementTree as ET

import eventeditor.container_xml as cxml


def dumps_actors(actor_payloads: typing.Iterable[typing.Dict[str, typing.Any]]) -> str:
    root = ET.Element('Actors')
    for payload in actor_payloads:
        actor_elem = ET.SubElement(root, 'Actor', {
            'name': payload.get('name', ''),
            'sub_name': payload.get('sub_name', ''),
            'argument_name': payload.get('argument_name', ''),
            'concurrent_clips': str(payload.get('concurrent_clips', 0xFFFF)),
        })
        argument_entry_point = payload.get('argument_entry_point')
        if argument_entry_point:
            actor_elem.set('argument_entry_point', argument_entry_point)

        actions_elem = ET.SubElement(actor_elem, 'Actions')
        for action in payload.get('actions', []):
            action_elem = ET.SubElement(actions_elem, 'Action')
            action_elem.text = action

        queries_elem = ET.SubElement(actor_elem, 'Queries')
        for query in payload.get('queries', []):
            query_elem = ET.SubElement(queries_elem, 'Query')
            query_elem.text = query

        params = payload.get('params')
        if params is not None:
            params_elem = ET.SubElement(actor_elem, 'Parameters')
            params_elem.append(ET.fromstring(cxml.dumps_container_dict(params)))

    return ET.tostring(root, encoding='unicode')


def loads_actors(xml_text: str) -> typing.List[typing.Dict[str, typing.Any]]:
    root = ET.fromstring(xml_text)
    if root.tag != 'Actors':
        raise ValueError('The XML root element must be <Actors>.')

    actors: typing.List[typing.Dict[str, typing.Any]] = []
    for actor_elem in root.findall('Actor'):
        payload: typing.Dict[str, typing.Any] = {
            'name': actor_elem.get('name', ''),
            'sub_name': actor_elem.get('sub_name', ''),
            'argument_name': actor_elem.get('argument_name', ''),
            'argument_entry_point': actor_elem.get('argument_entry_point') or None,
            'concurrent_clips': int(actor_elem.get('concurrent_clips', '65535')),
            'actions': [element.text or '' for element in actor_elem.findall('./Actions/Action')],
            'queries': [element.text or '' for element in actor_elem.findall('./Queries/Query')],
            'params': None,
        }

        params_container = actor_elem.find('./Parameters/Container')
        if params_container is not None:
            payload['params'] = cxml.loads_container_dict(
                ET.tostring(params_container, encoding='unicode')
            )

        actors.append(payload)

    return actors
