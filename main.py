import wechat_syncer
from utils import caichengyu


def main():
    caichengyu.init("chat_images")
    wechat_syncer.start()


if __name__ == '__main__':
    main()
