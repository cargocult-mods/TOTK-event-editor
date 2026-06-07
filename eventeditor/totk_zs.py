import functools
from pathlib import Path
import typing

import oead

try:
    import zstandard as zstd
except ImportError as exc:
    zstd = None
    _zstd_import_error = exc
else:
    _zstd_import_error = None


class ZstdSupportError(RuntimeError):
    pass


class MissingDictionaryPackError(ZstdSupportError):
    pass


_romfs_path: typing.Optional[Path] = None


def set_romfs_path(path: typing.Optional[str]) -> None:
    global _romfs_path
    _romfs_path = Path(path) if path else None


def get_romfs_path() -> typing.Optional[Path]:
    return _romfs_path


def is_compressed_path(path: str) -> bool:
    lower = path.lower()
    return lower.endswith('.zs') or lower.endswith('.zstd') or lower.endswith('.mc')


def _get_pack_path_from_root(root: Path) -> Path:
    if root.is_file():
        return root
    return root / 'Pack' / 'ZsDic.pack.zs'


def _iter_dictionary_pack_candidates(path: Path) -> typing.Iterable[Path]:
    seen: typing.Set[Path] = set()

    def yield_candidate(candidate: Path) -> typing.Iterator[Path]:
        resolved = candidate.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        if candidate.is_file():
            yield candidate

    if _romfs_path:
        yield from yield_candidate(_get_pack_path_from_root(_romfs_path))

    search_root = path if path.is_dir() else path.parent
    for parent in (search_root,) + tuple(search_root.parents):
        yield from yield_candidate(parent / 'Pack' / 'ZsDic.pack.zs')


def _resolve_dictionary_pack(path: str) -> Path:
    target = Path(path)
    for candidate in _iter_dictionary_pack_candidates(target):
        return candidate

    raise MissingDictionaryPackError(
        'TotK .zs support requires a valid RomFS root containing Pack/ZsDic.pack.zs.'
    )


class _ZstdContext:
    def __init__(self, dictionaries: typing.Dict[str, 'zstd.ZstdCompressionDict']) -> None:
        self._pack_decompressor = zstd.ZstdDecompressor(dict_data=dictionaries['pack.zsdic'])
        self._bcett_decompressor = zstd.ZstdDecompressor(dict_data=dictionaries['bcett.byml.zsdic'])
        self._zs_decompressor = zstd.ZstdDecompressor(dict_data=dictionaries['zs.zsdic'])
        self._magicless_decompressor = zstd.ZstdDecompressor(format=zstd.FORMAT_ZSTD1_MAGICLESS)

        self._pack_compressor = zstd.ZstdCompressor(dict_data=dictionaries['pack.zsdic'])
        self._bcett_compressor = zstd.ZstdCompressor(dict_data=dictionaries['bcett.byml.zsdic'])
        self._zs_compressor = zstd.ZstdCompressor(dict_data=dictionaries['zs.zsdic'])

    def decompress(self, path: str, data: bytes) -> bytes:
        lower = path.lower()
        if lower.endswith('.pack.zs'):
            return self._pack_decompressor.decompress(data)
        if lower.endswith('.bcett.byml.zs'):
            return self._bcett_decompressor.decompress(data)
        if lower.endswith('.mc'):
            return self._magicless_decompressor.decompress(data)
        return self._zs_decompressor.decompress(data)

    def compress(self, path: str, data: bytes) -> bytes:
        lower = path.lower()
        if lower.endswith('.pack.zs'):
            return self._pack_compressor.compress(data)
        if lower.endswith('.bcett.byml.zs'):
            return self._bcett_compressor.compress(data)
        return self._zs_compressor.compress(data)


@functools.lru_cache(maxsize=8)
def _get_context(pack_path: str) -> _ZstdContext:
    if zstd is None:
        raise ZstdSupportError(
            'The zstandard Python package is required for TotK .zs support.'
        ) from _zstd_import_error

    archive_data = zstd.ZstdDecompressor().decompress(Path(pack_path).read_bytes())
    archive = oead.Sarc(archive_data)
    dictionaries: typing.Dict[str, zstd.ZstdCompressionDict] = {
        file.name: zstd.ZstdCompressionDict(bytes(file.data)) for file in archive.get_files()
    }

    required_names = {'pack.zsdic', 'bcett.byml.zsdic', 'zs.zsdic'}
    missing = required_names.difference(dictionaries)
    if missing:
        missing_list = ', '.join(sorted(missing))
        raise ZstdSupportError(f'ZsDic pack is missing required dictionaries: {missing_list}')

    return _ZstdContext(dictionaries)


def decompress(path: str, data: bytes) -> bytes:
    if not is_compressed_path(path):
        return data
    return _get_context(str(_resolve_dictionary_pack(path))).decompress(path, data)


def compress(path: str, data: bytes) -> bytes:
    if not is_compressed_path(path):
        return data
    return _get_context(str(_resolve_dictionary_pack(path))).compress(path, data)
