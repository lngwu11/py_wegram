import wechat_syncer
from admin.maintenance import run_startup_maintenance
from utils import caichengyu


def main():
    run_startup_maintenance()
    caichengyu.init("chat_images")
    wechat_syncer.start()


if __name__ == '__main__':
    main()
