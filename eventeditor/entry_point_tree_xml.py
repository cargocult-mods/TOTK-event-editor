import typing
import xml.etree.ElementTree as ET

import eventeditor.container_xml as cxml


def _append_container(parent: ET.Element, tag: str, data: typing.Optional[typing.Dict[str, typing.Any]]) -> None:
    if data is None:
        return
    section = ET.SubElement(parent, tag)
    section.append(ET.fromstring(cxml.dumps_container_dict(data)))


def _read_container(parent: ET.Element, tag: str) -> typing.Optional[typing.Dict[str, typing.Any]]:
    container = parent.find(f'./{tag}/Container')
    if container is None:
        return None
    return cxml.loads_container_dict(ET.tostring(container, encoding='unicode'))


def dumps_payload(payload: typing.Dict[str, typing.Any]) -> str:
    root = ET.Element('EntryPointTrees', {'version': str(payload.get('version', 2))})

    actors_elem = ET.SubElement(root, 'Actors')
    for actor in payload.get('actors', []):
        actor_elem = ET.SubElement(actors_elem, 'Actor', {
            'name': actor['identifier'][0],
            'sub_name': actor['identifier'][1],
            'argument_name': actor.get('argument_name', ''),
            'concurrent_clips': str(actor.get('concurrent_clips', 0xFFFF)),
        })
        actions_elem = ET.SubElement(actor_elem, 'Actions')
        for action in actor.get('actions', []):
            child = ET.SubElement(actions_elem, 'Action')
            child.text = action
        queries_elem = ET.SubElement(actor_elem, 'Queries')
        for query in actor.get('queries', []):
            child = ET.SubElement(queries_elem, 'Query')
            child.text = query
        _append_container(actor_elem, 'Parameters', actor.get('params'))

    events_elem = ET.SubElement(root, 'Events')
    for record in payload.get('events', []):
        event_elem = ET.SubElement(events_elem, 'Event', {
            'source_idx': str(record['source_idx']),
            'kind': record['kind'],
        })
        if 'actor_key' in record:
            event_elem.set('actor_name', record['actor_key'][0])
            event_elem.set('actor_sub_name', record['actor_key'][1])
        if 'actor_action' in record:
            event_elem.set('actor_action', record['actor_action'])
        if 'actor_query' in record:
            event_elem.set('actor_query', record['actor_query'])
        if 'nxt' in record and record['nxt'] is not None:
            event_elem.set('nxt', str(record['nxt']))
        if 'join' in record and record['join'] is not None:
            event_elem.set('join', str(record['join']))
        if 'res_flowchart_name' in record:
            event_elem.set('res_flowchart_name', record.get('res_flowchart_name', ''))
        if 'entry_point_name' in record:
            event_elem.set('entry_point_name', record.get('entry_point_name', ''))

        if record.get('cases'):
            cases_elem = ET.SubElement(event_elem, 'Cases')
            for case in record['cases']:
                case_elem = ET.SubElement(cases_elem, 'Case', {'value': str(case['value'])})
                if case.get('target') is not None:
                    case_elem.set('target', str(case['target']))

        if record.get('forks'):
            forks_elem = ET.SubElement(event_elem, 'Forks')
            for target in record['forks']:
                if target is None:
                    continue
                ET.SubElement(forks_elem, 'Fork', {'target': str(target)})

        _append_container(event_elem, 'Parameters', record.get('params'))

    entry_points_elem = ET.SubElement(root, 'EntryPoints')
    for entry_point in payload.get('entry_points', []):
        entry_elem = ET.SubElement(entry_points_elem, 'EntryPoint', {
            'name': entry_point.get('name', ''),
            'main_event_name': entry_point.get('main_event_name', ''),
        })
        if entry_point.get('main_event_idx') is not None:
            entry_elem.set('main_event_idx', str(entry_point['main_event_idx']))
        _append_container(entry_elem, 'Items', entry_point.get('items') or {})

    return ET.tostring(root, encoding='unicode')


def loads_payload(xml_text: str) -> typing.Dict[str, typing.Any]:
    root = ET.fromstring(xml_text)
    if root.tag != 'EntryPointTrees':
        raise ValueError('The XML root element must be <EntryPointTrees>.')

    payload: typing.Dict[str, typing.Any] = {
        'version': int(root.get('version', '2')),
        'actors': [],
        'events': [],
        'entry_points': [],
    }

    for actor_elem in root.findall('./Actors/Actor'):
        payload['actors'].append({
            'identifier': (
                actor_elem.get('name', ''),
                actor_elem.get('sub_name', ''),
            ),
            'argument_name': actor_elem.get('argument_name', ''),
            'concurrent_clips': int(actor_elem.get('concurrent_clips', '65535')),
            'actions': [elem.text or '' for elem in actor_elem.findall('./Actions/Action')],
            'queries': [elem.text or '' for elem in actor_elem.findall('./Queries/Query')],
            'params': _read_container(actor_elem, 'Parameters'),
        })

    for event_elem in root.findall('./Events/Event'):
        record: typing.Dict[str, typing.Any] = {
            'source_idx': int(event_elem.get('source_idx', '0')),
            'kind': event_elem.get('kind', ''),
        }
        actor_name = event_elem.get('actor_name')
        actor_sub_name = event_elem.get('actor_sub_name')
        if actor_name is not None and actor_sub_name is not None:
            record['actor_key'] = (actor_name, actor_sub_name)
        if event_elem.get('actor_action') is not None:
            record['actor_action'] = event_elem.get('actor_action', '')
        if event_elem.get('actor_query') is not None:
            record['actor_query'] = event_elem.get('actor_query', '')
        if event_elem.get('nxt') is not None:
            record['nxt'] = int(event_elem.get('nxt', '0'))
        if event_elem.get('join') is not None:
            record['join'] = int(event_elem.get('join', '0'))
        if event_elem.get('res_flowchart_name') is not None:
            record['res_flowchart_name'] = event_elem.get('res_flowchart_name', '')
        if event_elem.get('entry_point_name') is not None:
            record['entry_point_name'] = event_elem.get('entry_point_name', '')

        cases = []
        for case_elem in event_elem.findall('./Cases/Case'):
            target = case_elem.get('target')
            if target is None:
                continue
            cases.append({
                'value': int(case_elem.get('value', '0')),
                'target': int(target),
            })
        if cases:
            record['cases'] = cases

        forks = []
        for fork_elem in event_elem.findall('./Forks/Fork'):
            target = fork_elem.get('target')
            if target is None:
                continue
            forks.append(int(target))
        if forks:
            record['forks'] = forks

        params = _read_container(event_elem, 'Parameters')
        if params is not None:
            record['params'] = params

        payload['events'].append(record)

    for entry_elem in root.findall('./EntryPoints/EntryPoint'):
        main_event_idx = entry_elem.get('main_event_idx')
        payload['entry_points'].append({
            'name': entry_elem.get('name', ''),
            'main_event_name': entry_elem.get('main_event_name', ''),
            'main_event_idx': int(main_event_idx) if main_event_idx is not None else None,
            'items': _read_container(entry_elem, 'Items') or {},
        })

    return payload
