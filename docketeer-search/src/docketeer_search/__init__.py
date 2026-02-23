"""Semantic search plugin for Docketeer."""

from docket import Docket

from docketeer_search.index import FastembedSearch

task_collections = ["docketeer_search.tasks:search_tasks"]


def create_search(*, docket: Docket, **_kwargs: object) -> FastembedSearch:
    return FastembedSearch(docket=docket)
