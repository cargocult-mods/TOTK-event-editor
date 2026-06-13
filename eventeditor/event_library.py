import copy
import hashlib
import json
import os
from pathlib import Path
import pickle
import re
import typing

import byml
from evfl import ActorIdentifier, EventFlow
from evfl.common import Argument
from evfl.event import ActionEvent, SwitchEvent
import oead

import eventeditor.totk_zs as totk_zs
import eventeditor.util as util


EVENT_LIBRARY_ACTION = 'action'
EVENT_LIBRARY_QUERY = 'query'
EVENT_LIBRARY_KINDS = (EVENT_LIBRARY_ACTION, EVENT_LIBRARY_QUERY)
EVENTFLOW_SCAN_SUFFIXES = (
    '.bfevfl.zs',
    '.bfevfl.zstd',
    '.bfevfl.gz',
    '.bfevfl',
    '.evfl.zs',
    '.evfl.zstd',
    '.evfl.gz',
    '.evfl',
)
MAX_ENTRY_EXAMPLES = 8
MAX_PARAMETER_EXAMPLES = 6
SOURCE_CURRENT_FILE = 'Current file'
SOURCE_MOD_AINB = 'Mod actor file'
SOURCE_MOD_OBSERVED = 'Mod flow examples'
SOURCE_VANILLA_AINB = 'Vanilla actor file'
SOURCE_VANILLA_OBSERVED = 'Vanilla flow examples'
SOURCE_GROUP_CURRENT = 'current'
SOURCE_GROUP_MOD = 'mod'
SOURCE_GROUP_VANILLA = 'vanilla'
SOURCE_GROUP_OTHER = 'other'
SOURCE_GROUP_ORDER = (SOURCE_GROUP_CURRENT, SOURCE_GROUP_MOD, SOURCE_GROUP_VANILLA, SOURCE_GROUP_OTHER)
SOURCE_GROUP_TITLES = {
    SOURCE_GROUP_CURRENT: 'Current',
    SOURCE_GROUP_MOD: 'Mod',
    SOURCE_GROUP_VANILLA: 'Vanilla',
    SOURCE_GROUP_OTHER: 'Other',
}
_AINB_STRING_RE = re.compile(rb'[A-Za-z0-9_./:-]{4,}')
_AINB_EXCLUDED_EVENT_NAMES = {
    'EventPerformer',
    'EventStartPos',
}
_EVENT_LIBRARY_CACHE = {}  # type: typing.Dict[typing.Tuple[str, str, str, str], typing.Tuple[typing.Any, 'EventLibraryResult']]
_VANILLA_EVENT_LIBRARY_CACHE = {}  # type: typing.Dict[typing.Tuple[str, str, str], 'EventLibraryResult']
_VANILLA_EVENT_LIBRARY_DISK_CACHE_VERSION = 3
_VANILLA_EVENT_LIBRARY_CACHE_ENV = 'TOTK_EVENTEDITOR_LIBRARY_CACHE_DIR'
_SOURCE_RANKS = {
    SOURCE_CURRENT_FILE: 0,
    SOURCE_MOD_AINB: 1,
    SOURCE_MOD_OBSERVED: 2,
    SOURCE_VANILLA_AINB: 3,
    SOURCE_VANILLA_OBSERVED: 4,
}


def is_event_library_kind(kind: str) -> bool:
    return kind in EVENT_LIBRARY_KINDS


def plain_value(value: typing.Any) -> typing.Any:
    if isinstance(value, Argument):
        return {'Argument': str(value)}
    if isinstance(value, ActorIdentifier):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [plain_value(item) for item in value]
    if isinstance(value, tuple):
        return [plain_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): plain_value(item) for key, item in value.items()}
    if hasattr(value, 'v'):
        return plain_value(value.v)
    return repr(value)


def format_library_value(value: typing.Any, quote_strings: bool = True) -> str:
    plain = plain_value(value)
    if not quote_strings:
        if isinstance(plain, str):
            return plain
        if isinstance(plain, dict) and set(plain.keys()) == {'Argument'}:
            return 'Argument: {}'.format(plain['Argument'])
    try:
        return json.dumps(plain, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(plain)


def _value_key(value: typing.Any) -> str:
    try:
        return json.dumps(plain_value(value), ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(value)


def eventflow_display_name(path_or_name: str) -> str:
    name = Path(str(path_or_name)).name if path_or_name else ''
    lower_name = name.lower()
    for suffix in sorted(EVENTFLOW_SCAN_SUFFIXES, key=len, reverse=True):
        if lower_name.endswith(suffix):
            return name[:-len(suffix)]
    return name


def source_group_for_label(source_label: str) -> str:
    if source_label == SOURCE_CURRENT_FILE:
        return SOURCE_GROUP_CURRENT
    if source_label.startswith('Mod '):
        return SOURCE_GROUP_MOD
    if source_label.startswith('Vanilla '):
        return SOURCE_GROUP_VANILLA
    return SOURCE_GROUP_OTHER


def source_group_title(group: str) -> str:
    return SOURCE_GROUP_TITLES.get(group, group.title())


def _case_values_summary(values: typing.Iterable[int]) -> str:
    sorted_values = sorted(int(value) for value in values)
    if not sorted_values:
        return ''
    ranges = []
    start = sorted_values[0]
    previous = sorted_values[0]
    for value in sorted_values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append((start, previous))
        start = value
        previous = value
    ranges.append((start, previous))
    return ', '.join(
        str(start) if start == end else '{}-{}'.format(start, end)
        for start, end in ranges
    )


def value_type_name(value: typing.Any) -> str:
    if isinstance(value, Argument):
        return 'Argument'
    if isinstance(value, bool):
        return 'Bool'
    if isinstance(value, int):
        return 'Int'
    if isinstance(value, float):
        return 'Float'
    if isinstance(value, str):
        return 'String'
    if isinstance(value, ActorIdentifier):
        return 'ActorIdentifier'
    if isinstance(value, list):
        if not value:
            return 'Array'
        item_types = []
        for item in value:
            type_name = value_type_name(item)
            if type_name not in item_types:
                item_types.append(type_name)
        if len(item_types) == 1:
            return '{}[]'.format(item_types[0])
        return 'Array'
    if value is None:
        return 'Unknown'
    return type(value).__name__


def default_value_for_type(type_name: str) -> typing.Any:
    normalized = type_name.lower()
    if normalized in ('bool', 'boolean'):
        return False
    if normalized in ('int', 's32', 'u32', 'int32'):
        return 0
    if normalized in ('float', 'f32'):
        return 0.0
    if normalized in ('string', 'str', 'std::string'):
        return ''
    if normalized in ('vec3f', 'vec3', 'vector3'):
        return [0.0, 0.0, 0.0]
    return None


class EventLibraryParameter:
    def __init__(self, name: str) -> None:
        self.name = name
        self.sources = []  # type: typing.List[str]
        self.defined_types = []  # type: typing.List[str]
        self.example_values = []  # type: typing.List[typing.Any]
        self._example_keys = set()  # type: typing.Set[str]
        self._example_sources = {}  # type: typing.Dict[str, typing.List[str]]
        self.default_value = None  # type: typing.Any
        self._default_values = []  # type: typing.List[typing.Tuple[str, typing.Any]]

    def add_source(self, source_label: str) -> None:
        if source_label and source_label not in self.sources:
            self.sources.append(source_label)

    def add_definition(self, type_name: str, default_value: typing.Any = None, source_label: str = '') -> None:
        self.add_source(source_label)
        if type_name and type_name not in self.defined_types:
            self.defined_types.append(type_name)
        if default_value is not None and self.default_value is None:
            self.default_value = copy.deepcopy(default_value)
        if default_value is not None:
            self._default_values.append((source_label, copy.deepcopy(default_value)))

    def add_example(self, value: typing.Any, source_label: str = '') -> None:
        self.add_source(source_label)
        key = _value_key(value)
        sources = self._example_sources.setdefault(key, [])
        if source_label and source_label not in sources:
            sources.append(source_label)
        if key in self._example_keys:
            return
        self._example_keys.add(key)
        if len(self.example_values) < MAX_PARAMETER_EXAMPLES:
            self.example_values.append(copy.deepcopy(value))
        type_name = value_type_name(value)
        if type_name not in self.defined_types:
            self.defined_types.append(type_name)

    def type_label(self) -> str:
        if not self.defined_types:
            return 'Unknown'
        return ' / '.join(self.defined_types)

    def has_source(self, source_predicate) -> bool:
        return any(source_predicate(source) for source in self.sources)

    def has_vanilla_source(self) -> bool:
        return self.has_source(lambda source: source.startswith('Vanilla '))

    def seed_value(self) -> typing.Any:
        if self.example_values:
            return copy.deepcopy(self.example_values[0])
        if self.default_value is not None:
            return copy.deepcopy(self.default_value)
        for type_name in self.defined_types:
            value = default_value_for_type(type_name)
            if value is not None:
                return value
        return None

    def seed_value_for_sources(self, source_predicate) -> typing.Any:
        for value in self.example_values:
            key = _value_key(value)
            if any(source_predicate(source) for source in self._example_sources.get(key, [])):
                return copy.deepcopy(value)
        for source_label, default_value in self._default_values:
            if source_predicate(source_label):
                return copy.deepcopy(default_value)
        if self.has_source(source_predicate):
            for type_name in self.defined_types:
                value = default_value_for_type(type_name)
                if value is not None:
                    return value
        return None


class EventLibraryExample:
    def __init__(self,
                 source_label: str,
                 source_file: str,
                 event_name: str,
                 params: typing.Optional[typing.Dict[str, typing.Any]],
                 cases: typing.Optional[typing.Dict[int, str]] = None) -> None:
        self.source_label = source_label
        self.source_file = source_file
        self.event_name = event_name
        self.params = copy.deepcopy(params) if params is not None else None
        self.cases = dict(cases or {})

    def display_name(self) -> str:
        source_name = eventflow_display_name(self.source_file)
        if source_name and self.event_name:
            return '{} / {}'.format(source_name, self.event_name)
        return source_name or self.event_name or self.source_label

    def display_label(self) -> str:
        return '{} ({})'.format(self.display_name(), self.source_label)

    def source_group(self) -> str:
        return source_group_for_label(self.source_label)


class EventLibraryEntry:
    def __init__(self, kind: str, name: str, source_rank: int) -> None:
        self.kind = kind
        self.name = name
        self.source_rank = source_rank
        self.sources = []  # type: typing.List[str]
        self.parameters = []  # type: typing.List[EventLibraryParameter]
        self._parameters_by_name = {}  # type: typing.Dict[str, EventLibraryParameter]
        self.examples = []  # type: typing.List[EventLibraryExample]
        self.all_examples = []  # type: typing.List[EventLibraryExample]
        self.example_count = 0
        self.case_targets = {}  # type: typing.Dict[int, typing.List[str]]

    def add_source(self, label: str, rank: int) -> None:
        self.source_rank = min(self.source_rank, rank)
        if label and label not in self.sources:
            self.sources.append(label)

    def add_parameter_definition(self, name: str, type_name: str, default_value: typing.Any = None) -> None:
        parameter = self._ensure_parameter(name)
        parameter.add_definition(type_name, default_value)

    def add_sourced_parameter_definition(self,
                                         name: str,
                                         type_name: str,
                                         default_value: typing.Any = None,
                                         source_label: str = '') -> None:
        parameter = self._ensure_parameter(name)
        parameter.add_definition(type_name, default_value, source_label)

    def add_observed(self,
                     source_label: str,
                     rank: int,
                     source_file: str,
                     event_name: str,
                     params: typing.Optional[typing.Dict[str, typing.Any]],
                     cases: typing.Optional[typing.Dict[int, str]] = None) -> None:
        self.add_source(source_label, rank)
        if params:
            for key, value in params.items():
                self._ensure_parameter(str(key)).add_example(value, source_label)
        if cases:
            for value, target in cases.items():
                targets = self.case_targets.setdefault(int(value), [])
                if target and target not in targets:
                    targets.append(target)
        self.example_count += 1
        example = EventLibraryExample(source_label, source_file, event_name, params, cases)
        self.all_examples.append(example)
        if len(self.examples) < MAX_ENTRY_EXAMPLES:
            self.examples.append(copy.deepcopy(example))

    def _ensure_parameter(self, name: str) -> EventLibraryParameter:
        parameter = self._parameters_by_name.get(name)
        if parameter is None:
            parameter = EventLibraryParameter(name)
            self._parameters_by_name[name] = parameter
            self.parameters.append(parameter)
        return parameter

    def parameter_summary(self) -> str:
        if not self.parameters:
            return '(none known)'
        return ', '.join(parameter.name for parameter in self.parameters)

    def source_summary(self) -> str:
        return ', '.join(self.sources) if self.sources else 'Unknown'

    def short_source_summary(self) -> str:
        groups = []
        if self.has_current_file_source():
            groups.append('current file')
        if self.has_mod_source():
            groups.append('mod')
        if self.has_vanilla_source():
            groups.append('vanilla')
        return ' + '.join(groups) if groups else 'unknown source'

    def has_current_file_source(self) -> bool:
        return SOURCE_CURRENT_FILE in self.sources

    def has_mod_source(self) -> bool:
        return any(source.startswith('Mod ') for source in self.sources)

    def has_vanilla_source(self) -> bool:
        return any(source.startswith('Vanilla ') for source in self.sources)

    def has_vanilla_baseline(self) -> bool:
        if self.vanilla_parameters():
            return True
        return any(
            example.source_label.startswith('Vanilla ')
            for example in self.all_observed_examples()
        )

    def case_count(self) -> int:
        return len(self.case_targets)

    def observed_example_count(self) -> int:
        return max(
            int(getattr(self, 'example_count', 0)),
            len(getattr(self, 'all_examples', [])),
            len(self.examples),
        )

    def example_count_label(self) -> str:
        observed_count = self.observed_example_count()
        if not observed_count:
            return ''
        if len(getattr(self, 'all_examples', [])) >= observed_count:
            return str(observed_count)
        if observed_count > len(self.examples):
            return '{}+'.format(len(self.examples))
        return str(observed_count)

    def all_observed_examples(self) -> typing.List[EventLibraryExample]:
        examples = getattr(self, 'all_examples', None)
        if examples is not None:
            return list(examples)
        return list(self.examples)

    def source_group_counts(self) -> typing.Dict[str, int]:
        counts = {group: 0 for group in SOURCE_GROUP_ORDER}
        for example in self.all_observed_examples():
            group = example.source_group()
            counts[group] = counts.get(group, 0) + 1
        return counts

    def examples_for_groups(self, groups: typing.Optional[typing.Iterable[str]] = None) -> typing.List[EventLibraryExample]:
        group_set = set(SOURCE_GROUP_ORDER if groups is None else groups)
        if not group_set:
            return []
        return [
            example for example in self.all_observed_examples()
            if example.source_group() in group_set
        ]

    def observed_example_count_for_groups(self, groups: typing.Optional[typing.Iterable[str]] = None) -> int:
        return len(self.examples_for_groups(groups))

    def preview_examples(self,
                         groups: typing.Optional[typing.Iterable[str]] = None,
                         limit: int = MAX_ENTRY_EXAMPLES) -> typing.List[EventLibraryExample]:
        group_set = set(SOURCE_GROUP_ORDER if groups is None else groups)
        examples = self.examples_for_groups(group_set)
        if len(examples) <= limit:
            return examples

        selected_groups = [group for group in SOURCE_GROUP_ORDER if group in group_set]
        buckets = {
            group: [example for example in examples if example.source_group() == group]
            for group in selected_groups
        }
        available_groups = [group for group in selected_groups if buckets.get(group)]
        if not available_groups:
            return []
        if len(available_groups) == 1:
            return buckets[available_groups[0]][:limit]

        quotas = {group: 1 for group in available_groups}
        remaining = max(0, limit - len(quotas))
        if all(group in available_groups for group in (SOURCE_GROUP_CURRENT, SOURCE_GROUP_MOD, SOURCE_GROUP_VANILLA)):
            preferred = {
                SOURCE_GROUP_CURRENT: 2,
                SOURCE_GROUP_MOD: 2,
                SOURCE_GROUP_VANILLA: 4,
                SOURCE_GROUP_OTHER: 1,
            }
            for group in available_groups:
                target = min(preferred.get(group, 1), len(buckets[group]))
                extra = max(0, target - quotas[group])
                take = min(extra, remaining)
                quotas[group] += take
                remaining -= take
                if remaining <= 0:
                    break
        while remaining > 0:
            grew = False
            for group in available_groups:
                if quotas[group] >= len(buckets[group]):
                    continue
                quotas[group] += 1
                remaining -= 1
                grew = True
                if remaining <= 0:
                    break
            if not grew:
                break

        chosen = []  # type: typing.List[EventLibraryExample]
        chosen_ids = set()  # type: typing.Set[int]
        for group in available_groups:
            for example in buckets[group][:quotas[group]]:
                chosen.append(example)
                chosen_ids.add(id(example))
        if len(chosen) >= limit:
            return chosen[:limit]
        for example in examples:
            if id(example) in chosen_ids:
                continue
            chosen.append(example)
            if len(chosen) >= limit:
                break
        return chosen

    def case_value_summary(self) -> str:
        return _case_values_summary(self.case_targets.keys())

    def vanilla_parameters(self) -> typing.List[EventLibraryParameter]:
        return [parameter for parameter in self.parameters if parameter.has_vanilla_source()]

    def vanilla_parameter_names(self) -> typing.List[str]:
        return [parameter.name for parameter in self.vanilla_parameters()]

    def list_summary(self) -> str:
        parts = []
        if self.parameters:
            parts.append('{} param{}'.format(len(self.parameters), '' if len(self.parameters) == 1 else 's'))
        else:
            parts.append('no known params')
        observed_count = self.observed_example_count()
        if observed_count:
            parts.append('{} example{}'.format(observed_count, '' if observed_count == 1 else 's'))
        parts.append(self.short_source_summary())
        return ', '.join(parts)

    def default_params(self) -> typing.Dict[str, typing.Any]:
        params = {}
        for parameter in self.parameters:
            value = parameter.seed_value()
            if value is not None:
                params[parameter.name] = value
        return params

    def usage_analysis(self) -> typing.Dict[str, typing.Any]:
        examples = self.all_observed_examples()
        param_counts = {}  # type: typing.Dict[str, int]
        value_counts = {}  # type: typing.Dict[str, typing.Dict[str, int]]
        case_set_counts = {}  # type: typing.Dict[typing.Tuple[int, ...], int]
        examples_with_params = 0
        for example in examples:
            params = example.params if isinstance(example.params, dict) else {}
            if params:
                examples_with_params += 1
            for key, value in params.items():
                key_text = str(key)
                param_counts[key_text] = param_counts.get(key_text, 0) + 1
                values = value_counts.setdefault(key_text, {})
                value_key = _value_key(value)
                values[value_key] = values.get(value_key, 0) + 1
            if example.cases:
                case_key = tuple(sorted(int(value) for value in example.cases.keys()))
                case_set_counts[case_key] = case_set_counts.get(case_key, 0) + 1

        vanilla_names = set(self.vanilla_parameter_names())
        if vanilla_names:
            expected_names = vanilla_names
        else:
            threshold = max(2, (examples_with_params + 1) // 2)
            expected_names = {
                name for name, count in param_counts.items()
                if count >= threshold
            }

        common_case_set = None
        if case_set_counts:
            common_case_set = max(case_set_counts.items(), key=lambda item: item[1])[0]

        return {
            'examples': examples,
            'expected_names': expected_names,
            'vanilla_names': vanilla_names,
            'param_counts': param_counts,
            'value_counts': value_counts,
            'case_set_counts': case_set_counts,
            'common_case_set': common_case_set,
        }

    def unusual_notes(self,
                      example: EventLibraryExample,
                      analysis: typing.Optional[typing.Dict[str, typing.Any]] = None) -> typing.List[str]:
        analysis = analysis or self.usage_analysis()
        notes = []  # type: typing.List[str]
        params = example.params if isinstance(example.params, dict) else {}
        expected_names = set(analysis.get('expected_names') or set())
        param_names = {str(name) for name in params.keys()}

        if expected_names:
            missing = sorted(expected_names - param_names)
            extra = sorted(param_names - expected_names)
            if missing:
                notes.append('Missing usual parameter{}: {}'.format(
                    '' if len(missing) == 1 else 's',
                    ', '.join(missing[:4]),
                ))
            if extra:
                baseline = 'vanilla' if analysis.get('vanilla_names') else 'usual'
                notes.append('Extra parameter{} beyond {} set: {}'.format(
                    '' if len(extra) == 1 else 's',
                    baseline,
                    ', '.join(extra[:4]),
                ))

        param_counts = analysis.get('param_counts') or {}
        value_counts = analysis.get('value_counts') or {}
        rare_value_keys = []
        for key, value in params.items():
            key_text = str(key)
            counts = value_counts.get(key_text, {})
            if param_counts.get(key_text, 0) < 4 or len(counts) <= 1:
                continue
            if counts.get(_value_key(value), 0) == 1:
                rare_value_keys.append(key_text)
        if rare_value_keys:
            notes.append('Rare value{} for: {}'.format(
                '' if len(rare_value_keys) == 1 else 's',
                ', '.join(rare_value_keys[:4]),
            ))

        if example.cases:
            case_key = tuple(sorted(int(value) for value in example.cases.keys()))
            case_set_counts = analysis.get('case_set_counts') or {}
            common_case_set = analysis.get('common_case_set')
            if common_case_set and case_key != common_case_set and case_set_counts.get(case_key, 0) == 1:
                notes.append('Unusual switch case set: {}'.format(_case_values_summary(case_key)))

        return notes

    def detail_text(self) -> str:
        lines = [
            self.name,
            'Type: {}'.format('Query' if self.kind == EVENT_LIBRARY_QUERY else 'Action'),
            'Sources: {}'.format(self.source_summary()),
            '',
            'Parameters:',
        ]
        if self.parameters:
            for parameter in self.parameters:
                lines.append('  {}: {}'.format(parameter.name, parameter.type_label()))
                if parameter.example_values:
                    examples = ', '.join(format_library_value(value) for value in parameter.example_values)
                    lines.append('    examples: {}'.format(examples))
        else:
            lines.append('  (none known)')

        if self.case_targets:
            value_word = 'value' if self.case_count() == 1 else 'values'
            lines.extend([
                '',
                'Observed switch cases: {} confirmed {} ({})'.format(
                    self.case_count(),
                    value_word,
                    self.case_value_summary(),
                ),
            ])

        observed_count = self.observed_example_count()
        preview_examples = self.preview_examples()
        if preview_examples:
            if observed_count > len(preview_examples):
                lines.extend(['', 'Examples (showing {} of {}):'.format(len(preview_examples), observed_count)])
            else:
                lines.extend(['', 'Examples:'])
            for example in preview_examples:
                lines.append('  {}'.format(example.display_label()))
                if example.params:
                    for key, value in example.params.items():
                        lines.append('    {}: {}'.format(key, format_library_value(value)))
                elif example.params is None:
                    lines.append('    params: (none)')
                if example.cases:
                    case_text = ', '.join(str(value) for value in sorted(example.cases.keys()))
                    lines.append('    cases: {}'.format(case_text))

        return '\n'.join(lines)


class EventLibraryResult:
    def __init__(self,
                 entries: typing.List[EventLibraryEntry],
                 errors: typing.List[str],
                 from_cache: bool = False,
                 source_fingerprint: typing.Any = None,
                 mod_context_enabled: bool = True) -> None:
        self.entries = entries
        self.errors = errors
        self.from_cache = from_cache
        self.source_fingerprint = source_fingerprint
        self.mod_context_enabled = mod_context_enabled

    def cached_copy(self) -> 'EventLibraryResult':
        return EventLibraryResult(
            self.entries,
            self.errors,
            True,
            self.source_fingerprint,
            getattr(self, 'mod_context_enabled', True),
        )


def _add_entry(builders: typing.Dict[str, EventLibraryEntry],
               kind: str,
               name: str,
               source_label: str,
               source_rank: int) -> EventLibraryEntry:
    entry = builders.get(name)
    if entry is None:
        entry = EventLibraryEntry(kind, name, source_rank)
        builders[name] = entry
    entry.add_source(source_label, source_rank)
    return entry


def _source_rank(source_label: str, fallback: int) -> int:
    return _SOURCE_RANKS.get(source_label, fallback)


def _merge_parameter(target: EventLibraryParameter, source: EventLibraryParameter) -> None:
    for source_label in source.sources:
        target.add_source(source_label)

    for type_name in source.defined_types:
        if type_name not in target.defined_types:
            target.defined_types.append(type_name)

    if target.default_value is None and source.default_value is not None:
        target.default_value = copy.deepcopy(source.default_value)

    existing_defaults = {
        (source_label, _value_key(default_value))
        for source_label, default_value in target._default_values
    }
    for source_label, default_value in source._default_values:
        key = (source_label, _value_key(default_value))
        if key in existing_defaults:
            continue
        target._default_values.append((source_label, copy.deepcopy(default_value)))
        existing_defaults.add(key)

    for value in source.example_values:
        key = _value_key(value)
        example_sources = source._example_sources.get(key, source.sources)
        for source_label in example_sources:
            target.add_example(value, source_label)


def _merge_entry_into_builders(builders: typing.Dict[str, EventLibraryEntry],
                               source_entry: EventLibraryEntry) -> None:
    target = builders.get(source_entry.name)
    if target is None:
        builders[source_entry.name] = copy.deepcopy(source_entry)
        return

    for source_label in source_entry.sources:
        target.add_source(source_label, _source_rank(source_label, source_entry.source_rank))

    target.example_count += source_entry.observed_example_count()

    for source_parameter in source_entry.parameters:
        _merge_parameter(target._ensure_parameter(source_parameter.name), source_parameter)

    for case_value, source_targets in source_entry.case_targets.items():
        targets = target.case_targets.setdefault(case_value, [])
        for source_target in source_targets:
            if source_target and source_target not in targets:
                targets.append(source_target)

    target_all_examples = getattr(target, 'all_examples', None)
    if target_all_examples is None:
        target.all_examples = list(target.examples)
    for example in source_entry.all_observed_examples():
        target.all_examples.append(copy.deepcopy(example))

    for example in source_entry.examples:
        if len(target.examples) >= MAX_ENTRY_EXAMPLES:
            break
        target.examples.append(copy.deepcopy(example))


def _merge_result_into_builders(builders: typing.Dict[str, EventLibraryEntry],
                                result: EventLibraryResult) -> None:
    for entry in result.entries:
        _merge_entry_into_builders(builders, entry)


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


def current_mod_eventflow_directories(flow_path: str) -> typing.List[Path]:
    directories = []  # type: typing.List[Path]
    if flow_path:
        directories.append(Path(flow_path).parent)

    owner_root = infer_eventflow_owner_root(flow_path)
    if owner_root:
        flow_parts = [part.lower() for part in Path(flow_path).parts]
        if 'romfs' in flow_parts:
            directories.append(owner_root / 'romfs' / 'Event' / 'EventFlow')
        directories.append(owner_root / 'Event' / 'EventFlow')

    return _unique_paths(directories)


def current_mod_roots(flow_path: str) -> typing.List[Path]:
    owner_root = infer_eventflow_owner_root(flow_path)
    return [owner_root] if owner_root else []


def _unique_paths(paths: typing.Iterable[Path]) -> typing.List[Path]:
    unique = []  # type: typing.List[Path]
    seen = set()  # type: typing.Set[str]
    for path in paths:
        try:
            key = str(path.resolve()) if path.exists() else str(path)
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _safe_path_key(path: typing.Optional[Path]) -> str:
    if not path:
        return ''
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _normalized_path_key(path: typing.Optional[Path]) -> str:
    return os.path.normcase(os.path.normpath(_safe_path_key(path))) if path else ''


def is_flow_path_in_vanilla_romfs(flow_path: str, vanilla_romfs: typing.Optional[Path]) -> bool:
    if not flow_path or not vanilla_romfs:
        return False
    flow_key = _normalized_path_key(Path(flow_path))
    vanilla_key = _normalized_path_key(Path(vanilla_romfs))
    if not flow_key or not vanilla_key:
        return False
    return flow_key == vanilla_key or flow_key.startswith(vanilla_key + os.sep)


def mod_context_enabled_for_flow_path(flow_path: str, vanilla_romfs: typing.Optional[Path]) -> bool:
    return not is_flow_path_in_vanilla_romfs(flow_path, vanilla_romfs)


def _safe_stat_signature(path: Path) -> typing.Tuple[str, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), -1, -1)
    return (str(path), int(stat.st_size), int(stat.st_mtime_ns))


def _eventflow_directory_signature(directory: Path) -> typing.Tuple[typing.Tuple[str, int, int], ...]:
    return tuple(_safe_stat_signature(path) for path in _iter_eventflow_files(directory))


def _actor_pack_signature(roots: typing.Iterable[Path], actor_name: str) -> typing.Tuple[typing.Tuple[str, int, int], ...]:
    signatures = []
    for root in _unique_paths(roots):
        for candidate in _actor_pack_candidates(root, actor_name):
            if candidate.is_file():
                signatures.append(_safe_stat_signature(candidate))
                break
    return tuple(signatures)


def build_actor_event_library_fingerprint(actor_name: str,
                                          kind: str,
                                          current_flow: typing.Optional[EventFlow] = None,
                                          flow_path: str = '',
                                          vanilla_romfs: typing.Optional[Path] = None,
                                          current_revision: int = 0) -> typing.Any:
    mod_context_enabled = mod_context_enabled_for_flow_path(flow_path, vanilla_romfs)
    mod_eventflow_dirs = current_mod_eventflow_directories(flow_path) if mod_context_enabled else []
    mod_roots = current_mod_roots(flow_path) if mod_context_enabled else []
    vanilla_root = Path(vanilla_romfs) if vanilla_romfs else None
    current_path = Path(flow_path) if flow_path else None
    return (
        actor_name,
        kind,
        mod_context_enabled,
        id(current_flow) if current_flow and not flow_path else 0,
        _safe_path_key(current_path),
        _safe_stat_signature(current_path) if current_path and current_path.is_file() else None,
        tuple((str(directory), _eventflow_directory_signature(directory)) for directory in mod_eventflow_dirs),
        _actor_pack_signature(mod_roots, actor_name),
        _safe_path_key(vanilla_root),
    )


def _cache_key(actor_name: str,
               kind: str,
               flow_path: str = '',
               vanilla_romfs: typing.Optional[Path] = None) -> typing.Tuple[str, str, str, str]:
    return (
        actor_name,
        kind,
        _safe_path_key(Path(flow_path) if flow_path else None),
        _safe_path_key(Path(vanilla_romfs) if vanilla_romfs else None),
    )


def _vanilla_cache_key(actor_name: str,
                       kind: str,
                       vanilla_romfs: typing.Optional[Path] = None) -> typing.Tuple[str, str, str]:
    return (
        actor_name,
        kind,
        _safe_path_key(Path(vanilla_romfs) if vanilla_romfs else None),
    )


def _vanilla_disk_cache_root() -> Path:
    override = os.environ.get(_VANILLA_EVENT_LIBRARY_CACHE_ENV)
    if override:
        return Path(override)

    if os.name == 'nt':
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if base:
            return Path(base) / 'eventeditor' / 'Cache' / 'event-library'

    base = os.environ.get('XDG_CACHE_HOME')
    if base:
        return Path(base) / 'eventeditor' / 'event-library'
    return Path.home() / '.cache' / 'eventeditor' / 'event-library'


def _vanilla_disk_cache_path(key: typing.Tuple[str, str, str]) -> Path:
    key_text = json.dumps(key, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(key_text.encode('utf-8')).hexdigest()
    return _vanilla_disk_cache_root() / 'vanilla-v{}-{}.pickle'.format(
        _VANILLA_EVENT_LIBRARY_DISK_CACHE_VERSION,
        digest,
    )


def _read_vanilla_disk_cache(key: typing.Tuple[str, str, str]) -> typing.Optional[EventLibraryResult]:
    path = _vanilla_disk_cache_path(key)
    try:
        with path.open('rb') as handle:
            payload = pickle.load(handle)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get('version') != _VANILLA_EVENT_LIBRARY_DISK_CACHE_VERSION:
        return None
    if tuple(payload.get('key', ())) != key:
        return None
    result = payload.get('result')
    if not isinstance(result, EventLibraryResult):
        return None
    return result


def _write_vanilla_disk_cache(key: typing.Tuple[str, str, str], result: EventLibraryResult) -> None:
    path = _vanilla_disk_cache_path(key)
    tmp_path = path.with_name('{}.{}.tmp'.format(path.name, os.getpid()))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'version': _VANILLA_EVENT_LIBRARY_DISK_CACHE_VERSION,
            'key': key,
            'result': result,
        }
        with tmp_path.open('wb') as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def clear_event_library_cache(clear_disk: bool = False) -> None:
    _EVENT_LIBRARY_CACHE.clear()
    _VANILLA_EVENT_LIBRARY_CACHE.clear()
    if not clear_disk:
        return
    try:
        for path in _vanilla_disk_cache_root().glob('vanilla-v{}-*.pickle'.format(_VANILLA_EVENT_LIBRARY_DISK_CACHE_VERSION)):
            try:
                path.unlink()
            except OSError:
                pass
    except OSError:
        pass


def is_actor_event_library_cache_current(actor_name: str,
                                         kind: str,
                                         current_flow: typing.Optional[EventFlow] = None,
                                         flow_path: str = '',
                                         vanilla_romfs: typing.Optional[Path] = None,
                                         current_revision: int = 0) -> bool:
    if not actor_name or not is_event_library_kind(kind):
        return False
    key = _cache_key(actor_name, kind, flow_path, vanilla_romfs)
    cached = _EVENT_LIBRARY_CACHE.get(key)
    if not cached:
        return False
    fingerprint = build_actor_event_library_fingerprint(
        actor_name,
        kind,
        current_flow=current_flow,
        flow_path=flow_path,
        vanilla_romfs=vanilla_romfs,
        current_revision=current_revision,
    )
    return cached[0] == fingerprint


def _iter_eventflow_files(directory: Path) -> typing.Iterable[Path]:
    if not directory or not directory.is_dir():
        return []

    paths = []  # type: typing.List[Path]
    seen = set()  # type: typing.Set[str]
    for suffix in EVENTFLOW_SCAN_SUFFIXES:
        for path in directory.glob('*{}'.format(suffix)):
            key = str(path)
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            paths.append(path)
    return sorted(paths, key=lambda value: value.name.lower())


def iter_event_flow_flowcharts(flow: typing.Optional[EventFlow]) -> typing.Iterable[typing.Any]:
    if not flow:
        return

    seen = set()  # type: typing.Set[int]

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


def _holder_text(ref: typing.Any, fallback_list: typing.Sequence[typing.Any]) -> str:
    value = getattr(ref, 'v', ref)
    if isinstance(value, int):
        try:
            value = fallback_list[value]
        except (IndexError, TypeError):
            return ''
    value = getattr(value, 'v', value)
    return str(value) if value is not None else ''


def _event_actor(event_data: typing.Any, flowchart: typing.Any) -> typing.Tuple[str, str, typing.Any]:
    actor_ref = getattr(event_data, 'actor', None)
    actor = getattr(actor_ref, 'v', actor_ref)
    if isinstance(actor, int):
        try:
            actor = flowchart.actors[actor]
        except (IndexError, AttributeError, TypeError):
            return '', '', None
    identifier = getattr(actor, 'identifier', None)
    if identifier is None:
        return str(actor) if actor is not None else '', str(actor) if actor is not None else '', actor
    return identifier.name, str(identifier), actor


def _container_params(container: typing.Any) -> typing.Optional[typing.Dict[str, typing.Any]]:
    if not container:
        return None
    data = getattr(container, 'data', None)
    if not isinstance(data, dict):
        return None
    return copy.deepcopy(data)


def _case_target_name(flowchart: typing.Any, ref: typing.Any) -> str:
    value = getattr(ref, 'v', ref)
    if isinstance(value, int):
        try:
            value = flowchart.events[value]
        except (IndexError, AttributeError, TypeError):
            return ''
    return getattr(value, 'name', '') or str(value or '')


def _scan_flow(flow: EventFlow,
               actor_name: str,
               kind: str,
               source_label: str,
               source_rank: int,
               source_file: str,
               builders: typing.Dict[str, EventLibraryEntry]) -> None:
    for flowchart in iter_event_flow_flowcharts(flow):
        for event in getattr(flowchart, 'events', []) or []:
            event_data = getattr(event, 'data', None)
            if kind == EVENT_LIBRARY_ACTION and not isinstance(event_data, ActionEvent):
                continue
            if kind == EVENT_LIBRARY_QUERY and not isinstance(event_data, SwitchEvent):
                continue

            event_actor_name, _actor_identifier, actor = _event_actor(event_data, flowchart)
            if event_actor_name != actor_name:
                continue

            if kind == EVENT_LIBRARY_ACTION:
                name = _holder_text(getattr(event_data, 'actor_action', None), getattr(actor, 'actions', []))
                cases = None
            else:
                name = _holder_text(getattr(event_data, 'actor_query', None), getattr(actor, 'queries', []))
                cases = {
                    int(value): _case_target_name(flowchart, ref)
                    for value, ref in getattr(event_data, 'cases', {}).items()
                }
            if not name:
                continue

            entry = _add_entry(builders, kind, name, source_label, source_rank)
            entry.add_observed(
                source_label,
                source_rank,
                source_file,
                getattr(event, 'name', ''),
                _container_params(getattr(event_data, 'params', None)),
                cases,
            )


def _read_eventflow(path: Path) -> EventFlow:
    flow = EventFlow()
    util.read_flow(str(path), flow)
    return flow


def _exception_summary(exc: Exception) -> str:
    text = str(exc).strip()
    class_name = type(exc).__name__
    if not text:
        return class_name
    if text.startswith(class_name):
        return text
    return '{}: {}'.format(class_name, text)


def _eventflow_skip_reason(exc: Exception) -> str:
    if isinstance(exc, (FileNotFoundError, PermissionError, OSError)):
        return 'Could not open EventFlow file'
    if isinstance(exc, totk_zs.MissingDictionaryPackError):
        return 'Missing ZsDic dictionary pack for compressed EventFlow'
    if isinstance(exc, totk_zs.ZstdSupportError):
        return 'Could not decompress compressed EventFlow'
    return 'Could not parse or decompress EventFlow'


def _actor_pack_skip_reason(exc: Exception) -> str:
    if isinstance(exc, (FileNotFoundError, PermissionError, OSError)):
        return 'Could not open actor pack'
    if isinstance(exc, totk_zs.MissingDictionaryPackError):
        return 'Missing ZsDic dictionary pack for compressed actor pack'
    if isinstance(exc, totk_zs.ZstdSupportError):
        return 'Could not decompress actor pack'
    return 'Could not decompress or open actor pack archive'


def _format_scan_error(path: Path, reason: str, exc: Exception) -> str:
    return '{} - {}: {}'.format(path.name, reason, _exception_summary(exc))


def _scan_eventflow_directories(directories: typing.Iterable[Path],
                                actor_name: str,
                                kind: str,
                                source_label: str,
                                source_rank: int,
                                builders: typing.Dict[str, EventLibraryEntry],
                                errors: typing.List[str],
                                skip_paths: typing.Optional[typing.Iterable[Path]] = None) -> None:
    skip_keys = {
        _safe_path_key(path).lower()
        for path in (skip_paths or [])
        if path
    }
    for directory in _unique_paths(directories):
        for path in _iter_eventflow_files(directory):
            if _safe_path_key(path).lower() in skip_keys:
                continue
            try:
                flow = _read_eventflow(path)
            except Exception as exc:
                errors.append(_format_scan_error(path, _eventflow_skip_reason(exc), exc))
                continue
            _scan_flow(flow, actor_name, kind, source_label, source_rank, path.name, builders)


def _actor_pack_candidates(root: Path, actor_name: str) -> typing.List[Path]:
    candidates = []  # type: typing.List[Path]
    for actor_root in (
        root / 'romfs' / 'Pack' / 'Actor',
        root / 'Pack' / 'Actor',
    ):
        candidates.append(actor_root / '{}.pack.zs'.format(actor_name))
        candidates.append(actor_root / '{}.pack'.format(actor_name))
    return _unique_paths(candidates)


def _read_actor_pack_files(path: Path) -> typing.Dict[str, bytes]:
    data = totk_zs.decompress(str(path), path.read_bytes())
    archive = oead.Sarc(data)
    return {file.name: bytes(file.data) for file in archive.get_files()}


def _event_unique_ain_name(files: typing.Dict[str, bytes], actor_name: str) -> str:
    for name, data in files.items():
        if not name.startswith('Component/EventPerformerParam/') or not name.endswith('.bgyml'):
            continue
        try:
            parsed = byml.Byml(data).parse()
        except Exception:
            continue
        event_unique_ain = parsed.get('EventUniqueAin') if isinstance(parsed, dict) else ''
        if not event_unique_ain:
            continue
        ain_name = Path(str(event_unique_ain).replace('\\', '/')).name
        if ain_name.endswith('.ain'):
            ain_name = ain_name[:-4] + '.ainb'
        elif not ain_name.endswith('.ainb'):
            ain_name += '.ainb'
        return 'AI/{}'.format(ain_name)
    return 'AI/{}.event.root.ainb'.format(actor_name)


def _find_ainb_data(files: typing.Dict[str, bytes], actor_name: str) -> typing.Optional[bytes]:
    preferred_name = _event_unique_ain_name(files, actor_name)
    if preferred_name in files:
        return files[preferred_name]
    preferred_base = Path(preferred_name).name.lower()
    for name, data in files.items():
        if name.lower().endswith('/{}'.format(preferred_base)):
            return data
    return None


def _ainb_name_kind(name: str) -> str:
    if name.startswith('EventQuery'):
        return EVENT_LIBRARY_QUERY
    if name.startswith('Event') and name not in _AINB_EXCLUDED_EVENT_NAMES:
        return EVENT_LIBRARY_ACTION
    return ''


def _scan_ainb_with_parser(data: bytes,
                           kind: str,
                           source_label: str,
                           source_rank: int,
                           builders: typing.Dict[str, EventLibraryEntry]) -> bool:
    try:
        from ainb import AINB  # type: ignore
    except Exception:
        return False

    try:
        ainb = AINB(data)
        nodes = ainb.output_dict.get('Nodes', [])
    except Exception:
        return False

    for node in nodes:
        if not isinstance(node, dict):
            continue
        name = node.get('Name')
        if not isinstance(name, str) or _ainb_name_kind(name) != kind:
            continue
        entry = _add_entry(builders, kind, name, source_label, source_rank)
        output_parameters = node.get('Output Parameters', {})
        if not isinstance(output_parameters, dict):
            continue
        for type_name, values in output_parameters.items():
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                parameter_name = value.get('Name')
                if isinstance(parameter_name, str) and parameter_name:
                    entry.add_sourced_parameter_definition(
                        parameter_name,
                        _ainb_parameter_type_name(str(type_name)),
                        value.get('Value', None),
                        source_label,
                    )
    return True


def _ainb_parameter_type_name(type_name: str) -> str:
    mapping = {
        'bool': 'Bool',
        'int': 'Int',
        'float': 'Float',
        'string': 'String',
        'vec3f': 'Vec3',
        'userdefined': 'UserDefined',
    }
    return mapping.get(type_name.lower(), type_name)


def _scan_ainb_strings(data: bytes,
                       kind: str,
                       source_label: str,
                       source_rank: int,
                       builders: typing.Dict[str, EventLibraryEntry]) -> None:
    for match in _AINB_STRING_RE.finditer(data):
        try:
            name = match.group().decode('utf-8')
        except UnicodeDecodeError:
            continue
        if '/' in name or '.' in name or ':' in name or '-' in name:
            continue
        if _ainb_name_kind(name) != kind:
            continue
        _add_entry(builders, kind, name, source_label, source_rank)


def _scan_actor_packs(roots: typing.Iterable[Path],
                      actor_name: str,
                      kind: str,
                      source_label: str,
                      source_rank: int,
                      builders: typing.Dict[str, EventLibraryEntry],
                      errors: typing.List[str]) -> None:
    for root in _unique_paths(roots):
        for candidate in _actor_pack_candidates(root, actor_name):
            if not candidate.is_file():
                continue
            try:
                files = _read_actor_pack_files(candidate)
                ainb_data = _find_ainb_data(files, actor_name)
            except Exception as exc:
                errors.append(_format_scan_error(candidate, _actor_pack_skip_reason(exc), exc))
                continue
            if not ainb_data:
                continue
            if not _scan_ainb_with_parser(ainb_data, kind, source_label, source_rank, builders):
                _scan_ainb_strings(ainb_data, kind, source_label, source_rank, builders)
            return


def _build_vanilla_actor_event_library(actor_name: str,
                                       kind: str,
                                       vanilla_romfs: typing.Optional[Path],
                                       use_cache: bool = True,
                                       force_rebuild: bool = False) -> EventLibraryResult:
    if not vanilla_romfs:
        return EventLibraryResult([], [])

    key = _vanilla_cache_key(actor_name, kind, vanilla_romfs)
    cached = _VANILLA_EVENT_LIBRARY_CACHE.get(key)
    if use_cache and not force_rebuild and cached:
        return cached.cached_copy()
    if use_cache and not force_rebuild:
        disk_cached = _read_vanilla_disk_cache(key)
        if disk_cached:
            _VANILLA_EVENT_LIBRARY_CACHE[key] = disk_cached
            return disk_cached.cached_copy()

    builders = {}  # type: typing.Dict[str, EventLibraryEntry]
    errors = []  # type: typing.List[str]
    vanilla_root = Path(vanilla_romfs)
    _scan_actor_packs([vanilla_root], actor_name, kind, SOURCE_VANILLA_AINB, 3, builders, errors)
    _scan_eventflow_directories([vanilla_root / 'Event' / 'EventFlow'], actor_name, kind, SOURCE_VANILLA_OBSERVED, 4, builders, errors)

    entries = sorted(builders.values(), key=lambda entry: (entry.source_rank, entry.name.lower()))
    result = EventLibraryResult(entries, errors, False, key)
    if use_cache:
        _VANILLA_EVENT_LIBRARY_CACHE[key] = result
        _write_vanilla_disk_cache(key, result)
    return result


def build_actor_event_library(actor_name: str,
                              kind: str,
                              current_flow: typing.Optional[EventFlow] = None,
                              flow_path: str = '',
                              vanilla_romfs: typing.Optional[Path] = None,
                              current_revision: int = 0,
                              use_cache: bool = True,
                              force_rebuild: bool = False) -> EventLibraryResult:
    if not actor_name or not is_event_library_kind(kind):
        return EventLibraryResult([], [])

    fingerprint = build_actor_event_library_fingerprint(
        actor_name,
        kind,
        current_flow=current_flow,
        flow_path=flow_path,
        vanilla_romfs=vanilla_romfs,
        current_revision=current_revision,
    )
    cache_key = _cache_key(actor_name, kind, flow_path, vanilla_romfs)
    cached = _EVENT_LIBRARY_CACHE.get(cache_key)
    if use_cache and not force_rebuild and cached and cached[0] == fingerprint:
        return cached[1].cached_copy()

    builders = {}  # type: typing.Dict[str, EventLibraryEntry]
    errors = []  # type: typing.List[str]
    mod_context_enabled = mod_context_enabled_for_flow_path(flow_path, vanilla_romfs)

    if current_flow:
        _scan_flow(current_flow, actor_name, kind, SOURCE_CURRENT_FILE, 0, Path(flow_path).name if flow_path else SOURCE_CURRENT_FILE, builders)

    if mod_context_enabled:
        mod_roots = current_mod_roots(flow_path)
        _scan_actor_packs(mod_roots, actor_name, kind, SOURCE_MOD_AINB, 1, builders, errors)
        _scan_eventflow_directories(
            current_mod_eventflow_directories(flow_path),
            actor_name,
            kind,
            SOURCE_MOD_OBSERVED,
            2,
            builders,
            errors,
            skip_paths=[Path(flow_path)] if current_flow and flow_path else None,
        )

    if vanilla_romfs:
        vanilla_result = _build_vanilla_actor_event_library(
            actor_name,
            kind,
            vanilla_romfs,
            use_cache=use_cache,
            force_rebuild=force_rebuild,
        )
        _merge_result_into_builders(builders, vanilla_result)
        errors.extend(vanilla_result.errors)

    entries = sorted(builders.values(), key=lambda entry: (entry.source_rank, entry.name.lower()))
    result = EventLibraryResult(entries, errors, False, fingerprint, mod_context_enabled)
    if use_cache:
        _EVENT_LIBRARY_CACHE[cache_key] = (fingerprint, result)
    return result
