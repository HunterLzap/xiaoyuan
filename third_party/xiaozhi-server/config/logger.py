import logging


class ModuleLogger(logging.LoggerAdapter):
    def bind(self, **fields):
        return ModuleLogger(self.logger, {**self.extra, **fields})


def setup_logging():
    return ModuleLogger(logging.getLogger("xiaozhi"), {})
