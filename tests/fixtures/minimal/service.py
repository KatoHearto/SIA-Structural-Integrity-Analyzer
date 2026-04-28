from base import Base


class Service(Base):
    def hook(self) -> int:
        return super().hook() + 1


def orchestrate() -> int:
    from util import helper

    return helper() + Service().hook()
