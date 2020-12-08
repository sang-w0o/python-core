import logging
from datetime import timedelta
from enum import Enum

import celery
from celery import Celery
from celery.apps.beat import Beat
from celery.apps.worker import Worker
from celery.schedules import crontab
from celery.signals import after_setup_task_logger

from spaceone.core import config
from spaceone.core.logger import FORMATTER_DEFAULT_TMPL, set_logger

DEFAULT_SPACEONE_BEAT = 'spaceone.core.celery.schedulers.SpaceOneScheduler'

# @after_setup_task_logger.connect
# def setup_task_logger(logger, *args, **kwargs):
#     print(logging.root.manager.loggerDict)
#     for handler in logger.handlers:
#         handler.setFormatter(
#             logging.Formatter(FORMATTER_DEFAULT_TMPL['standard']['format'],datefmt=FORMATTER_DEFAULT_TMPL['standard']['datefmt']))
#

@celery.signals.setup_logging.connect
def setup_logging(**kwargs):
    set_logger()
    if config.get_global('CELERY', {}).get('debug_mode'):
        logger = logging.getLogger('celery')
        logger.propagate = True
        logger.level = logging.DEBUG
        logger = logging.getLogger('celery.app.trace')
        logger.propagate = True
        logger.level = logging.DEBUG



app = Celery('spaceone')


class SERVER_MODE_ENUM(Enum):
    WORKER = 'WORKER'
    BEAT = 'BEAT'
    SPACEONE_BEAT = 'SPACEONE_BEAT'


def update_celery_config(app):
    conf = config.get_global()
    default_que = f"{conf.get('SERVICE', 'spaceone')}_q"
    app.conf.update(task_default_queue=default_que)
    app.conf.update(task_cls='spaceone.core.celery.tasks:BaseTask')
    celery_config = conf.get('CELERY', {})
    app.conf.update(**celery_config.get('config', {}))
    mode = app.conf.mode = celery_config.get('mode')

    if mode == 'BEAT':
        register_beat_schedules(app)

    # add default tasks
    app.autodiscover_tasks(['spaceone.core.celery', conf["PACKAGE"]], force=True)

    # add custom scheduler tasks
    app.autodiscover_tasks([conf["PACKAGE"]], related_name='task', force=True)


def parse_schedule(rule_type: str, rule: dict):
    if rule_type == 'interval':
        return timedelta(**{rule.get('period', 'seconds'): rule['every']})
    elif rule_type == 'cron':
        return crontab(**rule)
    else:
        raise NotImplementedError('UNSUPPORTED RULE_TYPE')


def register_beat_schedules(app):
    conf = config.get_global()
    schedules_config = conf.get('CELERY', {}).get('schedules', {})
    for name, sch_info in schedules_config.items():
        schedule = {
            "task": sch_info['task'],
            "schedule": parse_schedule(sch_info['rule_type'], sch_info['rule'])
        }
        if args := sch_info.get('args'):
            schedule['args'] = args
        if kwargs := sch_info.get('kwargs'):
            schedule['kwargs'] = kwargs
        app.conf.beat_schedule[name]= schedule


def serve():
    # set_logger()
    update_celery_config(app)
    server_mode = app.conf.get('mode', SERVER_MODE_ENUM.WORKER.value)
    if server_mode == SERVER_MODE_ENUM.BEAT.value:
        Beat(app=app, loglevel='DEBUG').run()
    elif server_mode == SERVER_MODE_ENUM.SPACEONE_BEAT.value:
        app.conf.update(beat_scheduler=DEFAULT_SPACEONE_BEAT)
        Beat(app=app, loglevel='DEBUG').run()
    else:
        Worker(app=app).start()
