import logging
from pathlib import Path
from copy import deepcopy
from abc import ABC, abstractmethod
from typing import (Generic, TypeVar,
                    Protocol, runtime_checkable)

import orjson

from ..models import ValidationError


logger = logging.getLogger(__name__)


@runtime_checkable
class ModelProtocol(Protocol):
    data: dict
    def __init__(self, data: dict) -> None: ...

ModelT = TypeVar('ModelT', bound=ModelProtocol)


class BaseQGroups(ABC, Generic[ModelT]):
    """Базовый класс для работы с JSON файлом групп."""

    ModelClass: type[ModelT]
    
    def __init__(self, path_to_json: str | Path | None = None) -> None:
        self._json_cache: bytes | None = None
        self._path: Path | None = None

        self._init_groups()
        self.load_json(path_to_json)

    def _init_groups(self, data: dict | None = None) -> None:
        """Функция объединения данных."""
        self._groups = self.ModelClass(data=(data or {}))
        self._data = self._groups.data
        self._invalidate_cache()

    def _is_normal_data(self, data: dict) -> bool:
        try: self.ModelClass(data=data)
        except ValidationError as e:
            logger.error("Ошибка валидации класса %s : %s",
                         type(self.ModelClass), e)
            return False
        return True

    def _is_normal_json(self) -> bool:
        assert self._path is not None
        if not self._path.exists():
            logger.error("Переданного (%s) пути не существует", self._path)
            return False
        try:
            data = orjson.loads(self._path.read_bytes())
        except Exception as err:
            logger.error("Некорректная структура json файла: %s", err)
            return False
        return self._is_normal_data(data)

    def _create_json(self) -> None:
        assert self._path is not None
    
        self._path.parent.mkdir(parents=True, exist_ok=True)

        if self._path.exists():
            index = 1
            while True:
                backup_path = self._path.parent / f"{self._path.stem}_{index}{self._path.suffix}"
                if not backup_path.exists():
                    self._path.rename(backup_path)
                    logger.info("Файл переименован -> %s", self._path)
                    break
                index += 1
        
        self._path.write_bytes(self._orjson_bytes({}))
        logger.info("Создан новый %s", self._path)

    def _read_json(self) -> None:
        assert self._path is not None
        data = orjson.loads(self._path.read_bytes())
        self._init_groups(data=data)

    def _update_json(self) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        
        data = self._orjson_bytes(self._data)
        self._path.write_bytes(data)
        self._invalidate_cache()

    def _invalidate_cache(self) -> None:
        self._json_cache = None

    @abstractmethod
    def _merge(self, *datas: dict) -> dict:
        """Функция объединения данных"""
        pass

    def _orjson_bytes(self, data: dict) -> bytes:
        return orjson.dumps(
            data, option=orjson.OPT_INDENT_2 | 
                         orjson.OPT_SORT_KEYS | 
                         orjson.OPT_NON_STR_KEYS)

    def load_json(self, path_to_json: str | Path | None) -> None:
        """Функция подключения JSON файла"""
        self._path = Path(path_to_json) if path_to_json is not None else None
        
        if self._path is not None:
            if not self._is_normal_json():
                self._create_json()
            self._read_json()

    def load_data(self, data: dict) -> None:
        """Функция загрузки данных"""
        if self._is_normal_data(data):
            new_data = self._merge(self._data, data)
            self._init_groups(data=new_data)
            if self._path:
                self._update_json()
        else:
            logger.error("json данные не имеют смысла")

    def get_all_data_bytes(self) -> bytes:
        """Получить все данные в виде сериализованного JSON (с кэшированием)"""
        if self._json_cache is not None:
            return self._json_cache
        
        self._json_cache = self._orjson_bytes(self._data)
        return self._json_cache

    def get_all_data_str(self) -> str:
        """Получить все данные в виде JSON строки (с кэшированием)"""
        return self.get_all_data_bytes().decode('utf-8')

    @property
    def data(self) -> dict:
        """Получение данных в виде словаря"""
        return deepcopy(self._data)
    
    @property
    def path(self) -> Path | None:
        """Получение пути к файлу"""
        return deepcopy(self._path)
