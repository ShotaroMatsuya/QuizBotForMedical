import json
import os
import time

import boto3
import click
import tqdm


@click.command()
@click.argument("jsonfile", required=True, type=click.File("r"), nargs=1)
@click.argument("table", required=True, type=str, nargs=1)
@click.option("--profile", "-p", default="default", help="ローカルAWSプロフィール")
@click.option("--region", "-r", nargs=1, help="DynamoDBに設置するリージョン")
@click.option("--overwrite-endpoint", nargs=1, help="ローカルDynamoDBエンドポイント")
@click.option(
    "--writerate", default=5, type=int, nargs=1, help="WCU 1秒あたりの書き込む速度(default:5)"
)
def cmd(jsonfile, table, profile, region, overwrite_endpoint, writerate):
    """
    JSONファイルをDynamoDBにインポート
        [JSONFILE] jsonローカルパス\n
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
        click.echo("リージョンが設定されていないため、デフォルトap-northeast-1にセット")
        region = "ap-northeast-1"
    session = boto3.session.Session(profile_name=profile, region_name=region)

    # DynamoDB　エンドポイントとテーブル名
    if overwrite_endpoint:
        endpointUrl = overwrite_endpoint
    else:
        endpointUrl = "https://dynamodb." + region + ".amazonaws.com"
    dynamodb = session.resource("dynamodb", endpoint_url=endpointUrl)
    table = dynamodb.Table(table)
    click.echo(endpointUrl)
    items = json.load(jsonfile)
    # DynamoDBに書き込む
    with table.batch_writer() as batch:
        for item in items:
            print(item)
            batch.put_item(Item=item)

            # プロビジョンしたWCUと合わせる
            time.sleep(1 / writerate)
