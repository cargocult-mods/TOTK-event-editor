import html
import json
from pathlib import Path
import typing


TestBuildInfo = typing.Dict[str, typing.Any]


def load_test_build_info(path: Path) -> typing.Optional[TestBuildInfo]:
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None
    beta = data.get('beta')
    built_at = data.get('built_at')
    intended_features = data.get('intended_features')
    if not isinstance(beta, str) or not beta.strip():
        return None
    if not isinstance(built_at, str) or not built_at.strip():
        return None
    if (
        not isinstance(intended_features, list)
        or not intended_features
        or not all(isinstance(feature, str) and feature.strip() for feature in intended_features)
    ):
        return None
    return {
        'beta': beta.strip(),
        'built_at': built_at.strip(),
        'intended_features': [feature.strip() for feature in intended_features],
    }


def build_about_version_html(
    version: str,
    test_build_info: typing.Optional[TestBuildInfo],
) -> str:
    escaped_version = html.escape(str(version))
    if not test_build_info:
        return f'<p><small>Version: {escaped_version}</small></p>'

    beta = html.escape(str(test_build_info['beta']))
    built_at = html.escape(str(test_build_info['built_at']))
    features = ''.join(
        f'<li>{html.escape(str(feature))}</li>'
        for feature in test_build_info['intended_features']
    )
    return (
        f'<p>Version: {escaped_version} {beta}, built {built_at}</p>'
        '<p><b>Intended new features:</b></p>'
        f'<ul>{features}</ul>'
    )
