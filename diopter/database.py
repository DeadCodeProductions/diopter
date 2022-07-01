from __future__ import annotations

import hashlib
import zlib
from abc import ABC
from copy import deepcopy
from typing import Any, Optional

import sqlalchemy
import sqlalchemy.types as types
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    and_,
    exists,
    select,
)
from sqlalchemy.orm import Mapped, Session, declarative_base, relationship

Base = declarative_base()


def compress(s: str) -> bytes:
    return zlib.compress(s.encode("utf-8"), level=9)


def decompress(s: bytes) -> str:
    return zlib.decompress(s).decode("utf-8")


class CompressedString(types.TypeDecorator[str]):

    impl = types.BLOB

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[bytes]:
        if value is None:
            return None
        return compress(value)

    def process_result_value(self, value: bytes, dialect: Any) -> str:
        return decompress(value)


class HashableStringList(list[str]):
    def __eq__(self, other) -> bool:
        if not isinstance(other, HashableStringList):
            return False
        r1 = hash("||".join(sorted(self) if not self.is_empty() else ["||EMPTY||"]))
        r2 = hash("||".join(sorted(other) if not self.is_empty() else ["||EMPTY||"]))
        return r2 == r1

    def __hash__(self) -> int:
        tmp = sorted(self)
        res = hash("||".join(tmp if not self.is_empty() else ["||EMPTY||"]))
        return res

    def is_empty(self) -> bool:
        return len(self) == 0


class CompressedStringList(types.TypeDecorator[HashableStringList]):

    impl = types.BLOB

    # duckdb-engine does not support caching
    # cache_ok = True

    def process_bind_param(
        self, value: Optional[HashableStringList], dialect: Any
    ) -> Optional[bytes]:
        if value is None:
            return None
        if not value:
            return compress("||EMPTY||")
        return compress("||".join(sorted(value)))

    def process_result_value(self, value: bytes, dialect: Any) -> HashableStringList:
        res = decompress(value)
        if res == "||EMPTY||":
            return HashableStringList()
        return HashableStringList(res.split("||"))


class Code(Base):
    __tablename__ = "code"

    id: Mapped[str] = Column(String(40), primary_key=True, nullable=False)
    code: Mapped[str] = Column(CompressedString(), nullable=False)

    def __repr__(self) -> str:
        return f"{self.id!r} {self.code!r}"

    @staticmethod
    def make(code: str) -> Code:
        # TODO: make better constructor
        code_sha1 = hashlib.sha1(code.encode("utf-8")).hexdigest()
        return Code(id=code_sha1, code=code)


case_id_seq = sqlalchemy.Sequence("case_id_seq")


class CompilerSetting(Base):
    __tablename__ = "compiler_setting"

    id = Column(Integer(), sqlalchemy.Sequence("compiler_id_seq"), autoincrement=True)
    name: Mapped[str] = Column(String(10), primary_key=True)
    rev: Mapped[str] = Column(String(40), primary_key=True)
    opt_level: Mapped[str] = Column(String(1), primary_key=True)
    additional_flags: Mapped[list[str]] = Column(
        CompressedStringList(), primary_key=True
    )

    # def __eq__(self, other: object) -> bool:
    #    if not isinstance(other, CompilerSetting):
    #        return False
    #    return self.name == other.name and self.rev == other.rev and self.opt_level == other.opt_level and self.additional_flags == other.additional_flags

    # def __hash__(self) -> int:
    #    return hash(hash(self.name) + hash(self.rev) + hash(self.opt_level) + hash(self.additional_flags))

    def __repr__(self) -> str:
        return f"{self.name} {self.rev} {self.opt_level} {self.additional_flags}"

    def get_flag_string(self) -> str:
        return f"-O{self.opt_level} " + " ".join(self.additional_flags)

    def copy_override(
        self,
        name: Optional[str] = None,
        rev: Optional[str] = None,
        opt_level: Optional[str] = None,
        additional_flags: Optional[HashableStringList] = None,
    ) -> CompilerSetting:

        cleared_name = name if name else deepcopy(self.name)
        cleared_rev = rev if rev else deepcopy(self.rev)
        cleared_opt_level = opt_level if opt_level else deepcopy(self.opt_level)
        cleared_additional_flags = (
            additional_flags if additional_flags else deepcopy(self.additional_flags)
        )

        return CompilerSetting(
            name=cleared_name,
            rev=cleared_rev,
            opt_level=cleared_opt_level,
            additional_flags=cleared_additional_flags,
        )

    @staticmethod
    def get_from_db_or_new(
        session: Session,
        name: str,
        rev: str,
        opt_level: str,
        additional_flags: list[str],
    ) -> CompilerSetting:
        # TODO: Is this needed when we already have session.merge?
        additional_flags_ = HashableStringList(additional_flags)

        stmt = exists(CompilerSetting).where(
            and_(
                CompilerSetting.rev.is_(rev),
                CompilerSetting.opt_level.is_(opt_level),
            )
        )
        stmt_select = select(CompilerSetting).where(
            and_(
                CompilerSetting.rev.is_(rev),
                CompilerSetting.opt_level.is_(opt_level),
                CompilerSetting.additional_flags.is_(additional_flags_),
            )
        )
        if session.query(stmt).scalar():
            setting = session.scalar(stmt_select)
            return setting
        else:
            setting = CompilerSetting(
                name=name,
                rev=rev,
                opt_level=opt_level,
                additional_flags=additional_flags_,
            )
            return setting

    # def __deepcopy__(self, memo: dict[int, Any]) -> CompilerSetting:
    #    cls = self.__class__
    #    result = cls.__new__(cls)
    #    memo[id(self)] = result
    #    for k, v in self.__dict__.items():
    #        if k != "id":
    #            setattr(result, k, deepcopy(v, memo))
    #        else:
    #            setattr(result, k, None)
    #    return result


class BaseCase(Base):

    __tablename__ = "cases"
    id = Column(
        Integer(),
        case_id_seq,
        server_default=case_id_seq.next_value(),
        primary_key=True,
    )

    type = Column(String(20))

    bisection = Column(String(40))

    code_id = Column(String(40), ForeignKey("code.id"), nullable=False)
    original: Mapped[Code] = relationship("Code", foreign_keys="BaseCase.code_id")

    reduced_id = Column(String(40), ForeignKey("code.id"))
    reduced: Mapped[Optional[Code]] = relationship(
        "Code", foreign_keys="BaseCase.reduced_id"
    )

    __mapper_args__ = {
        "polymorphic_on": type,
        "polymorphic_identity": "basecase",
    }


# class Case(BaseCase):
#    massaged_id = Column(String(40), ForeignKey("code.id"))
#    massaged: Mapped[Optional[Code]] = relationship("Code", foreign_keys="Case.massaged_id")
#
#    __mapper_args__ = {
#        "polymorphic_identity": "case",
#    }


# class Case(Base):
#
#    __tablename__ = "cases"
#
#    id = Column(Integer(), autoincrement='auto')
#
#    bisection = Column(String(40))
#    code_id = Column(String(40), ForeignKey("code.id"), nullable=False, primary_key=True)
#    reduced_id = Column(String(40), ForeignKey("code.id"))
#    test_setting_id = Column(Integer(), ForeignKey("test_setting.id"))
#
#    original: Mapped[Code] = relationship("Code", foreign_keys="Case.code_id")
#
#    reduced: Mapped[Optional[Code]] = relationship("Code", foreign_keys="Case.reduced_id")
#
#
#    bad_setting_id = Column(Integer(), ForeignKey("compiler_setting.id"))
#    bad_setting = relationship("CompilerSetting", foreign_keys="Case.bad_setting_id")
#
#    test_setting = relationship("TestSetting", foreign_keys="Case.test_setting_id", cascade="all")
