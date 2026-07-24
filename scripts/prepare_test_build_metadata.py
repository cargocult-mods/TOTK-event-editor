import argparse
from datetime import datetime
import json
from pathlib import Path


DEFAULT_OUTPUT = Path('eventeditor/assets/test_build_info.json')


def format_build_timestamp(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    meridiem = 'am' if moment.hour < 12 else 'pm'
    return (
        f'{moment.day}/{moment.month}/{moment.year} '
        f'{hour}:{moment.minute:02d}{meridiem}'
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Prepare About-dialog metadata for a non-production EventEditor build.',
    )
    parser.add_argument('--beta', required=True, help='Test build label, for example beta4.')
    parser.add_argument(
        '--feature',
        action='append',
        required=True,
        dest='features',
        help='An intended feature. Repeat for each feature.',
    )
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = {
        'beta': args.beta.strip(),
        'built_at': format_build_timestamp(datetime.now()),
        'intended_features': [feature.strip() for feature in args.features],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    print(args.output)


if __name__ == '__main__':
    main()
