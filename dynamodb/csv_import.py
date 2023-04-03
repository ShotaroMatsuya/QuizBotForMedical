import os
import time
from csv import reader
from decimal import Decimal

import boto3
import click


@click.command()
@click.argument("csvfile", required=True, type=str, nargs=1)
@click.argument("table", required=True, type=str, nargs=1)
@click.option("--profile", "-p", default="default", help="ローカルAWSプロフィール")
@click.option(
    "--delimiter",
    "-d",
    default=",",
    nargs=1,
    help="Delimiter for csv records (default=',')",
)
@click.option("--region", "-r", nargs=1, help="DynamoDBに設置するリージョン")
@click.option("--overwrite-endpoint", nargs=1, help="ローカルDynamoDBエンドポイント")
@click.option(
    "--writerate", default=5, type=int, nargs=1, help="WCU　1秒あたりの書き込む速度 (default:5)"
)
def cmd(csvfile, table, profile, region, overwrite_endpoint, writerate, delimiter):
    """
    DynamoDBのマネジメントコンソールでエクスポートしたCSVをインポートするPythonスクリプト\n
        [CSVFILE] CSVローカルパス\n
        [TABLE] ImportするDynamoDB テーブル名
    \f

    """
    # オプションをチェック
    profile_check = [
        profile,
        os.environ.get("AWS_PROFILE"),
        os.environ.get("AWS_DEFAULT_PROFILE"),
    ]
    profile = next(p for p in profile_check if p)
    session = boto3.session.Session(profile_name=profile)

    try:
        region_check = [
            region,
            session.region_name,
            os.environ.get("AWS_REGION"),
            os.environ.get("AWS_DEFAULT_REGION"),
        ]
        region = next(r for r in region_check if r)
    except StopIteration:
        print("リージョンが設定されていないため、デフォルトap-northeast-1にセットします。")
        region = "ap-northeast-1"
    session = boto3.session.Session(profile_name=profile, region_name=region)

    # DynamoDB エンドポイントとテーブル名
    if overwrite_endpoint:
        endpointUrl = overwrite_endpoint
    else:
        endpointUrl = "https://dynamodb." + region + ".amazonaws.com"
    dynamodb = session.resource("dynamodb", endpoint_url=endpointUrl)
    table = dynamodb.Table(table)
    print(endpointUrl)

    # DynamoDBに書き込む
    with open(csvfile) as csv_file:
        tokens = reader(csv_file, delimiter=str(delimiter))
        print(tokens)
        # ヘッダー
        header = next(tokens)
        # コンテンツ読み込む
        for token in tokens:
            print(token)
            item = {}
            for i, val in enumerate(token):
                print("======")
                print(val)
                # DynamoDBの属性名はHeaderから取り出す
                key = header[i]
                # タイプがNumberの場合はCastが必要です。
                # if val_type == "(N)" and val:
                #     val = Decimal(val) if float(val) else int(val)
                item[key] = val
            table.put_item(Item=item)

            # プロビジョンしたWCUと合わせる
            time.sleep(1 / writerate)


if __name__ == "__main__":
    cmd()
