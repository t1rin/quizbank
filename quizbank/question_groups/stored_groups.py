import logging
from copy import deepcopy
from random import shuffle, choice, sample

from .base_groups import BaseQGroups
from ..types import StoredMode, StoredAnswer, StoredGroups
from ..models import (StoredQGroupsModel, QItem,
                      ValidationError)


logger = logging.getLogger(__name__)


class StoredQGroups(BaseQGroups[StoredQGroupsModel]):
    """Класс полноценной работы с JSON файлом групп."""

    ModelClass = StoredQGroupsModel

    def _merge(self, *datas: dict) -> dict:
        """Функция объединения данных."""
        result: StoredGroups = {}

        if not datas:
            return result
    
        for data in datas:
            for group_name, group_data in data.items():
                if group_name not in result:
                    result[group_name] = {StoredMode.QUESTION: {},
                                          StoredMode.ANSWER: {}}
                for mode in [StoredMode.QUESTION, StoredMode.ANSWER]:
                    if mode not in group_data:
                        continue
                    for title, answers in group_data[mode].items():
                        if title not in result[group_name][mode]:
                            result[group_name][mode][title] = []
                        result[group_name][mode][title].extend(answers)
                        
                        seen_texts = set()
                        unique_answers = []
                        for answer in result[group_name][mode][title]:
                            answer_text = answer[0]
                            if answer_text not in seen_texts:
                                seen_texts.add(answer_text)
                                unique_answers.append(answer)
                            else:
                                logging.warning(
                                    "Дубликат ответа '%s' в '%s' группы '%s'",
                                    answer_text, title, group_name
                                )
                    
                        result[group_name][mode][title] = unique_answers
                        # result[group_name][mode][title] = list(
                        #     set([*result[group_name][mode][title], *answers]))
        return result

    def _validate_str(self, **fields: str) -> bool:
        """Проверяет, что все переданные значения являются строками."""
        bad = [name for name, value in fields.items()
               if not isinstance(value, str)]
        if bad:
            logger.error("Ожидается строковый тип для: %s", ", ".join(bad))
            return False
        return True

    def _dedupe_answers(self, answers: list[StoredAnswer], *,
                        title: str, group: str) -> list[StoredAnswer]:
        """Убирает дубликаты ответов по тексту, логируя каждый из них."""
        seen: set[str] = set()
        unique: list[StoredAnswer] = []
        for answer_text, is_right in answers:
            if answer_text not in seen:
                seen.add(answer_text)
                unique.append((answer_text, is_right))
            else:
                logger.warning(
                    "Дубликат ответа '%s' в '%s' группы '%s'",
                    answer_text, title, group)
        return unique

    def _save(self) -> None:
        """Персистит изменения на диск (если подключён JSON) и сбрасывает кэш."""
        if self._path:
            self._update_json()
        else:
            self._invalidate_cache()

    def _get_bucket(self, group: str, reverse: bool = False,
                    ) -> dict[str, list[StoredAnswer]] | None:
        """Возвращает словарь {title: answers} для группы/режима, либо None."""
        if group not in self._data:
            logger.error("Группа '%s' не найдена", group)
            return None
        qmode = StoredMode.ANSWER if reverse else StoredMode.QUESTION
        return self._data[group][qmode]

    def add_question(self, group: str, title: str,
                     right_answers: list[str],
                     wrong_answers: list[str],
                     reverse: bool = False) -> bool:
        if self._path and not self._is_normal_json():
            self._create_json()

        try:
            QItem(group=group, title=title,
                  right_answers=right_answers,
                  wrong_answers=wrong_answers)
        except ValidationError as err:
            logger.error("%s (Ожидается" + 
                         " group -> [str], key -> [str]," + 
                         " right_answers -> list[str]," +
                         " wrong_answers -> list[str])", err)
            return False

        qmode = (StoredMode.ANSWER if reverse
                 else StoredMode.QUESTION)
        if group not in self._data:
            self._data[group] = {StoredMode.QUESTION: {},
                                 StoredMode.ANSWER: {}}

        answers = [*[(ans, True ) for ans in right_answers],
                   *[(ans, False) for ans in wrong_answers]]

        bucket = self._data[group][qmode]
        if title not in bucket:
            bucket[title] = answers
        else:
            bucket[title] = self._dedupe_answers(
                [*bucket[title], *answers], title=title, group=group)

        self._save()
        return True

    def rename_question(self, group: str, old_title: str, new_title: str,
                        reverse: bool = False, overwrite: bool = False,
                        ) -> bool:
        if not self._validate_str(group=group, old_title=old_title,
                                  new_title=new_title):
            return False

        bucket = self._get_bucket(group, reverse)
        if bucket is None:
            return False

        if old_title not in bucket:
            logger.error("Вопрос '%s' не найден в группе '%s'",
                         old_title, group)
            return False

        if old_title == new_title:
            return True

        if new_title in bucket:
            if not overwrite:
                logger.error(
                    "Вопрос '%s' уже существует в группе '%s'; "
                    "передайте overwrite=True для объединения ответов",
                    new_title, group)
                return False
            bucket[new_title] = self._dedupe_answers(
                [*bucket[new_title], *bucket[old_title]],
                title=new_title, group=group)
            del bucket[old_title]
        else:
            bucket[new_title] = bucket.pop(old_title)

        self._save()
        return True

    def remove_question(self, group: str, title: str,
                        reverse: bool = False) -> bool:
        if not self._validate_str(group=group, title=title):
            return False

        bucket = self._get_bucket(group, reverse)
        if bucket is None:
            return False

        if title not in bucket:
            logger.error("Вопрос '%s' не найден в группе '%s'", title, group)
            return False

        del bucket[title]
        self._save()
        return True

    def add_answer(self, group: str, title: str, answer: str,
                   is_right: bool = False, reverse: bool = False) -> bool:
        if not self._validate_str(group=group, title=title, answer=answer):
            return False

        bucket = self._get_bucket(group, reverse)
        if bucket is None:
            return False

        if title not in bucket:
            logger.error(
                "Вопрос '%s' не найден в группе '%s'; используйте "
                "add_question для создания нового вопроса", title, group)
            return False

        answers = bucket[title]
        if any(text == answer for text, _ in answers):
            logger.warning(
                "Ответ '%s' уже существует у вопроса '%s'", answer, title)
            return False

        answers.append((answer, is_right))
        self._save()
        return True

    def rename_answer(self, group: str, title: str,
                      old_answer: str, new_answer: str,
                      reverse: bool = False) -> bool:
        if not self._validate_str(group=group, title=title,
                                  old_answer=old_answer,
                                  new_answer=new_answer):
            return False

        bucket = self._get_bucket(group, reverse)
        if bucket is None:
            return False

        if title not in bucket:
            logger.error("Вопрос '%s' не найден в группе '%s'", title, group)
            return False

        answers = bucket[title]
        texts = [text for text, _ in answers]

        if old_answer not in texts:
            logger.error(
                "Ответ '%s' не найден у вопроса '%s'", old_answer, title)
            return False

        if old_answer == new_answer:
            return True

        if new_answer in texts:
            logger.error(
                "Ответ '%s' уже существует у вопроса '%s'",
                new_answer, title)
            return False

        idx = texts.index(old_answer)
        is_right = answers[idx][1]
        answers[idx] = (new_answer, is_right)

        self._save()
        return True

    def remove_answer(self, group: str, title: str, answer: str,
                      reverse: bool = False) -> bool:
        if not self._validate_str(group=group, title=title, answer=answer):
            return False

        bucket = self._get_bucket(group, reverse)
        if bucket is None:
            return False

        if title not in bucket:
            logger.error("Вопрос '%s' не найден в группе '%s'", title, group)
            return False

        answers = bucket[title]
        for index, (text, is_right) in enumerate(answers):
            if text != answer:
                continue

            right_count = sum(1 for _, r in answers if r)
            if is_right and right_count <= 1:
                logger.error(
                    "Нельзя удалить единственный правильный ответ "
                    "вопроса '%s'", title)
                return False

            del answers[index]
            self._save()
            return True

        logger.error("Ответ '%s' не найден у вопроса '%s'", answer, title)
        return False

    def get_groups(self) -> list[str]:
        return list(self._data.keys())

    def get_qitems(self, group: str,
                   reverse: bool = False,
                   ) -> list[QItem] | None:
        if group not in self._data.keys():
            return None

        qmode = (StoredMode.ANSWER if reverse
                 else StoredMode.QUESTION)
        qitems_source = self._data[group][qmode]

        qitems = []
        for title, answers in qitems_source.items():
            right_answers, wrong_answers = [], []
            for ans in answers:
                if ans[1]: right_answers.append(ans[0])
                else:      wrong_answers.append(ans[0])
                    
            qitems.append(QItem(group=group,title=title,
                                right_answers=right_answers,
                                wrong_answers=wrong_answers))
        return qitems

    def _building_question(self, group: str, title: str,
                           answers: list[StoredAnswer],
                           quantity: int, quantity_right: int = 1,
                           ) -> QItem | None:
        """Состовляет экземпляр класса QItem
        с количеством правильных ответов quantity_right,
        если они имеются"""

        if (quantity < 2) or (quantity_right < 1) or (quantity_right > quantity):
            logger.error("Некорректное количество вариантов ответа")
            return None
        
        if len(answers) < quantity:
            logger.warning(
                "Для вопроса '%s' недостаточно ответов (%s), нужно %s",
                title, len(answers), quantity)

        right_answers: list[str] = []
        wrong_answers: list[str] = []
        for answer_text, is_right in answers:
            if is_right:
                right_answers.append(answer_text)
            else:
                wrong_answers.append(answer_text)
    
        if not right_answers:
            logger.error("Не найден правильный ответ для вопроса '%s'", title)
            return None
        
        q_right = min(len(right_answers), quantity_right)
        right_answers = sample(right_answers, q_right)

        q_wrong = min(len(wrong_answers), quantity - quantity_right)
        wrong_answers = sample(wrong_answers, q_wrong)
    
        return QItem(group=group, title=title,
                     right_answers=right_answers,
                     wrong_answers=wrong_answers)

    def get_question(self, group: str, title: str,
                     reverse: bool = False,
                     quantity_ans: int = 3,
                     quantity_right: int = 1,
                     ) -> QItem | None:
        if any(not isinstance(name, str) for name in [title, group]):
            logger.error("Ожидается group -> [str], title -> [str]")
            return None
        if group not in self.get_groups():
            logger.error("Не найдена группа " + group)
            return None

        qmode = (StoredMode.ANSWER if reverse
                 else StoredMode.QUESTION)
        if title not in self._data[group][qmode].keys():
            logger.error("title \"" + title + "\" не найден")
            return None

        answers = deepcopy(self._data[group][qmode][title])
        shuffle(answers)

        return self._building_question(group, title, answers,
                                       quantity_ans, quantity_right)


    def get_rand_question(self,
                          group: str | None = None,
                          reverse: bool = False,
                          quantity_ans: int = 3,
                          quantity_right: int = 1,
                          ) -> QItem | None:
        if not self._data:
            logger.warning("Вопросов нет")
            return None
    
        if group is None:
            group = choice(self.get_groups())
    
        if group not in self.get_groups():
            logger.error("Группа '%s' не найдена", group)
            return None

        qmode = (StoredMode.ANSWER if reverse
                 else StoredMode.QUESTION)
        qitems_source = self._data[group][qmode]
    
        if not qitems_source:
            logger.warning("В группе '%s' нет вопросов", group)
            return None
    
        title = choice(list(qitems_source.keys()))
        answers = deepcopy(qitems_source[title])
    
        shuffle(answers)
    
        return self._building_question(group, title, answers,
                                       quantity_ans, quantity_right)