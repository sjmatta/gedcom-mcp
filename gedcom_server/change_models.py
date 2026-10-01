"""Strict operation schemas, loaded only when record editing is discovered."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class OperationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FieldPath(OperationModel):
    tag: str
    index: int = Field(ge=0)


class AddNote(OperationModel):
    op: Literal["add_note"]
    record_id: str
    text: str


class AddSource(OperationModel):
    op: Literal["add_source"]
    title: str
    author: str = ""
    publication: str = ""


class AddEvent(OperationModel):
    op: Literal["add_event"]
    record_id: str
    tag: str
    source_id: str
    date: str = ""
    place: str = ""
    description: str = ""
    page: str = ""


class AddCitation(OperationModel):
    op: Literal["add_citation"]
    record_id: str
    path: list[FieldPath]
    source_id: str
    page: str = ""


class ReplaceValue(OperationModel):
    op: Literal["replace_value"]
    record_id: str
    path: list[FieldPath]
    old_value: str
    value: str


class AddIndividual(OperationModel):
    op: Literal["add_individual"]
    individual_id: str
    name: str
    sex: Literal["M", "F", "U"] = "U"
    note: str = ""


class UpdateName(OperationModel):
    op: Literal["update_name"]
    individual_id: str
    old_name: str
    name: str
    given_name: str
    surname: str
    name_index: int = Field(default=0, ge=0)


class AddFamily(OperationModel):
    op: Literal["add_family"]
    family_id: str


class AddRelationship(OperationModel):
    op: Literal["add_relationship"]
    family_id: str
    individual_id: str
    role: Literal["HUSB", "WIFE", "CHIL"]
    pedigree: str = ""
    status: str = ""


class RemoveRelationship(OperationModel):
    op: Literal["remove_relationship"]
    family_id: str
    individual_id: str
    role: Literal["HUSB", "WIFE", "CHIL"]
    force: bool = False


class DeleteIndividual(OperationModel):
    op: Literal["delete_individual"]
    individual_id: str
    force: bool = False


class DeleteIndividuals(OperationModel):
    op: Literal["delete_individuals"]
    individual_ids: list[str]
    force: bool = False


class DeleteFamily(OperationModel):
    op: Literal["delete_family"]
    family_id: str
    force: bool = False


class DeleteFamilies(OperationModel):
    op: Literal["delete_families"]
    family_ids: list[str]
    force: bool = False


class MergeIndividuals(OperationModel):
    op: Literal["merge_individuals"]
    source_id: str
    target_id: str
    identity_evidence: str
    force: bool = False


ChangeOperation = Annotated[
    AddNote
    | AddSource
    | AddEvent
    | AddCitation
    | ReplaceValue
    | AddIndividual
    | UpdateName
    | AddFamily
    | AddRelationship
    | RemoveRelationship
    | DeleteIndividual
    | DeleteIndividuals
    | DeleteFamily
    | DeleteFamilies
    | MergeIndividuals,
    Field(discriminator="op"),
]
ChangeBatch = Annotated[list[ChangeOperation], Field(min_length=1, max_length=50)]
