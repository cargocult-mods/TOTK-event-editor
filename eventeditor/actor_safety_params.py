import typing


PLACEHOLDER_ACTOR_NAME = '<placeholder actor>'


# Conservative baseline observed on vanilla TOTK EventFlow actors. Some fields
# may turn out to be optional, but omitting the entire parameter container can
# crash the game and these defaults have no known downside.
ACTOR_SAFETY_PARAM_DEFAULTS = {
    'EventMemberCreateMethod': 0,
    'IsGrounding': False,
    'IsWorld': False,
    'UseEventModelAnime': '',
    'UseEventAS': '',
    'IsBindNearestActor': False,
}


class ActorSafetyParamFinding(typing.NamedTuple):
    actor: typing.Any
    flow_name: str
    actor_name: str
    missing_keys: typing.Tuple[str, ...]


class ActorSafetyParamFindings(typing.NamedTuple):
    no_params: typing.List[ActorSafetyParamFinding]
    missing_some: typing.List[ActorSafetyParamFinding]


def default_actor_safety_params() -> typing.Dict[str, typing.Any]:
    return dict(ACTOR_SAFETY_PARAM_DEFAULTS)


def _iter_flowcharts(flow: typing.Any) -> typing.Iterable[typing.Any]:
    if not flow:
        return

    seen = set()
    candidates = [getattr(flow, 'flowchart', None)]
    for attr_name in ('flowcharts', 'flow_charts'):
        collection = getattr(flow, attr_name, None)
        if not collection:
            continue
        values = collection.values() if isinstance(collection, dict) else getattr(collection, 'data', collection)
        candidates.extend(getattr(item, 'v', item) for item in values)

    for flowchart in candidates:
        if flowchart is None or id(flowchart) in seen:
            continue
        seen.add(id(flowchart))
        yield flowchart


def _actor_display_name(actor: typing.Any) -> str:
    identifier = getattr(actor, 'identifier', None)
    name = getattr(identifier, 'name', '') or '<unnamed actor>'
    sub_name = getattr(identifier, 'sub_name', '') or ''
    return '{}[{}]'.format(name, sub_name) if sub_name else name


def _unwrap_reference(value: typing.Any) -> typing.Any:
    for _ in range(8):
        next_value = getattr(value, 'v', None)
        if next_value is None or next_value is value:
            return value
        value = next_value
    return value


def _referenced_actor_ids(flowchart: typing.Any) -> typing.Set[int]:
    referenced = set()
    for event in getattr(flowchart, 'events', []) or []:
        data = getattr(event, 'data', None)
        actor_ref = getattr(data, 'actor', None)
        actor = _unwrap_reference(actor_ref)
        if actor is not None:
            referenced.add(id(actor))
    return referenced


def collect_actor_safety_param_findings(flow: typing.Any) -> ActorSafetyParamFindings:
    no_params = []
    missing_some = []

    for flowchart in _iter_flowcharts(flow):
        flow_name = getattr(flowchart, 'name', '') or '<unnamed flowchart>'
        referenced_actor_ids = _referenced_actor_ids(flowchart)
        for actor in getattr(flowchart, 'actors', []) or []:
            actor_name = _actor_display_name(actor)
            if actor_name == PLACEHOLDER_ACTOR_NAME and id(actor) not in referenced_actor_ids:
                continue
            params = getattr(actor, 'params', None)
            data = getattr(params, 'data', None) if params is not None else None
            missing = tuple(
                key for key in ACTOR_SAFETY_PARAM_DEFAULTS
                if not isinstance(data, dict) or key not in data
            )
            if not isinstance(data, dict) or not data:
                no_params.append(ActorSafetyParamFinding(actor, flow_name, actor_name, missing))
            elif missing:
                missing_some.append(ActorSafetyParamFinding(actor, flow_name, actor_name, missing))

    return ActorSafetyParamFindings(no_params, missing_some)


def ensure_actor_safety_params(
    actor: typing.Any,
    container_factory: typing.Callable[[], typing.Any],
) -> bool:
    params = getattr(actor, 'params', None)
    data = getattr(params, 'data', None) if params is not None else None
    if not isinstance(data, dict):
        params = container_factory()
        actor.params = params
        data = params.data

    changed = False
    for key, value in ACTOR_SAFETY_PARAM_DEFAULTS.items():
        if key not in data:
            data[key] = value
            changed = True
    return changed


def actor_safety_findings_text(
    findings: typing.Sequence[ActorSafetyParamFinding],
    include_missing_keys: bool,
    limit: int = 30,
) -> str:
    lines = []
    for finding in findings[:limit]:
        line = '- {} / {}'.format(finding.flow_name, finding.actor_name)
        if include_missing_keys:
            line += ': missing {}'.format(', '.join(finding.missing_keys))
        lines.append(line)
    if len(findings) > limit:
        lines.append('- ...and {} more'.format(len(findings) - limit))
    return '\n'.join(lines)


def repair_actor_safety_params(
    findings: typing.Iterable[ActorSafetyParamFinding],
    container_factory: typing.Callable[[], typing.Any],
) -> int:
    repaired = 0
    for finding in findings:
        if ensure_actor_safety_params(finding.actor, container_factory):
            repaired += 1
    return repaired
