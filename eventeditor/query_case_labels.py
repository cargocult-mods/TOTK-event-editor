import typing

from eventeditor.boolean_query_polarity import audited_case_label as audited_boolean_case_label


def _numbered_labels(*labels: str) -> typing.Dict[int, str]:
    return {
        value: '{} ({})'.format(value, label)
        for value, label in enumerate(labels)
    }


# Curated from explicit branch labels and ExecuteEventSetQueryValue results in
# vanilla actor event-root AINBs. Entries belong here only when the returned
# case values and their meanings are direct engine-graph evidence.
QUERY_CASE_LABELS = {
    'GameDataActor::EventQueryIsGameDataInt': _numbered_labels(
        'is less than', 'equal', 'is more than'
    ),
    'GameDataActor::EventQueryIsGameDataFloat': _numbered_labels(
        'is less than', 'equal', 'is more than'
    ),
    'GameDataActor::EventQueryIsGameDataEnum': _numbered_labels(
        'equal', 'not equal'
    ),
    'GameDataActor::EventQueryIsGameDataString64': _numbered_labels(
        'equal', 'not equal'
    ),
    'GameDataActor::EventQueryBranchByDyeColor': _numbered_labels(
        'invalid color',
        'blue',
        'red',
        'yellow',
        'white',
        'black',
        'purple',
        'green',
        'light blue',
        'navy',
        'orange',
        'pink',
        'crimson',
        'light yellow',
        'brown',
        'gray',
    ),
    'GameSystemActor::EventQueryTalkChoice2': _numbered_labels(
        'choice 1', 'choice 2'
    ),
    'GameSystemActor::EventQueryTalkChoice3': _numbered_labels(
        'choice 1', 'choice 2', 'choice 3'
    ),
    'GameSystemActor::EventQueryTalkChoice4': _numbered_labels(
        'choice 1', 'choice 2', 'choice 3', 'choice 4'
    ),
    'GameSystemActor::EventQueryTalkChoice8': _numbered_labels(
        'choice 1',
        'choice 2',
        'choice 3',
        'choice 4',
        'choice 5',
        'choice 6',
        'choice 7',
        'choice 8',
    ),
    'GameSystemActor::EventQueryHasRuppe': _numbered_labels(
        'has enough rupees', 'does not have enough rupees'
    ),
    'GameSystemActor::EventQueryHasRuppeSpecifyGameData': _numbered_labels(
        'has enough rupees', 'does not have enough rupees'
    ),
    'GameSystemActor::EventQueryPictureBookRegisteredEnemyNum': _numbered_labels(
        'is less than', 'equal', 'is more than'
    ),
    'EventWorldManagerController::EventQueryWeather': _numbered_labels(
        'clear',
        'cloudy',
        'rain',
        'heavy rain',
        'snow',
        'heavy snow',
        'storm',
        'thunderstorm',
        'sun shower',
    ),
    'EventWorldManagerController::EventQueryTimeDivision': _numbered_labels(
        'morning A, 04:00+',
        'morning B, 07:00+',
        'day A, 10:00+',
        'day B, 13:00+',
        'evening A, 17:00+',
        'evening B, 19:00+',
        'night A, 21:00+',
        'night B, 00:00+',
    ),
    'ChallengeSystemActor::EventQueryInputSageType': _numbered_labels(
        'Zora sage',
        'Goron sage',
        'Gerudo sage',
        'Rito sage',
        'Zonai sage',
        'not a sage',
    ),
    'PouchSystemActor::EventQueryCheckPouchContentCategory': _numbered_labels(
        'weapon',
        'bow',
        'arrow',
        'shield',
        'armor',
        'material',
        'food',
        'special part',
        'key item',
        'rupee',
        'other',
    ),
    'PouchSystemActor::EventQueryCheckSellResult': {
        0: '0 (can sell)',
        1: '1 (cannot sell)',
        2: '2 (cannot sell: equipped)',
    },
}


def audited_case_label(
    actor_name: str,
    query_name: str,
    value: typing.Any,
) -> typing.Optional[str]:
    labels = QUERY_CASE_LABELS.get('{}::{}'.format(actor_name, query_name))
    if labels is not None:
        try:
            case_value = int(value)
        except (TypeError, ValueError):
            return None
        return labels.get(case_value)
    return audited_boolean_case_label(actor_name, query_name, value)
