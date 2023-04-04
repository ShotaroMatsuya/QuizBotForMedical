import json
import logging
import os
import random
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def decimal_default_proc(obj):
    if isinstance(obj, Decimal):
        return int(obj)
    raise TypeError


def try_ex(func):
    try:
        return func()
    except KeyError:
        return None


def get_slots(intent_request):
    return intent_request["sessionState"]["intent"]["slots"]


def get_slot(intent_request, slotName):
    slots = get_slots(intent_request)
    if slots is not None and slotName in slots and slots[slotName] is not None:
        return (
            slots[slotName]["value"]["interpretedValue"]
            if "interpretedValue" in slots[slotName]["value"]
            else slots[slotName]["value"]["originalValue"]
        )
    else:
        return None


def get_session_attributes(intent_request):
    sessionState = intent_request["sessionState"]
    if "sessionAttributes" in sessionState:
        return sessionState["sessionAttributes"]

    return {}


def clear_session_attributes(intent_request):
    sessionState = intent_request["sessionState"]
    if "sessionAttributes" in sessionState:
        sessionState["sessionAttributes"] = {}


def elicit_intent(intent_request, session_attributes, message, response_card):
    return {
        "sessionState": {
            "dialogAction": {"type": "ElicitIntent"},
            "sessionAttributes": session_attributes,
        },
        "messages": [*message, response_card] if response_card is not None else message,
        "requestAttributes": intent_request["requestAttributes"]
        if "requestAttributes" in intent_request
        else None,
    }


def elicit_slot(
    intent_request,
    session_attributes,
    intent_name,
    slots,
    slot_to_elicit,
    message,  # list
    response_card,
):
    return {
        "sessionState": {
            "dialogAction": {"slotToElicit": slot_to_elicit, "type": "ElicitSlot"},
            "intent": {
                "name": intent_name,
                "slots": slots,
            },
            "sessionAttributes": session_attributes,
        },
        "messages": [*message, response_card] if response_card is not None else message,
        "requestAttributes": intent_request["requestAttributes"]
        if "requestAttributes" in intent_request
        else None,
    }


def confirm_intent(
    intent_request, session_attributes, intent_name, slots, message, response_card
):
    return {
        "sessionState": {
            "dialogAction": {"type": "ConfirmIntent"},  # 確認させる
            "intent": {"name": intent_name, "slots": slots, "state": "InProgress"},
            "sessionAttributes": session_attributes,
        },
        "messages": [*message, response_card] if response_card is not None else message,
        "requestAttributes": intent_request["requestAttributes"]
        if "requestAttributes" in intent_request
        else None,
    }


def close(intent_request, session_attributes, fulfillment_state, message):
    intent_request["sessionState"]["intent"]["state"] = fulfillment_state
    return {
        "sessionState": {
            "sessionAttributes": session_attributes,
            "dialogAction": {"type": "Close"},
            "intent": intent_request["sessionState"]["intent"],
        },
        "messages": message,
        "sessionId": intent_request["sessionId"],
        "requestAttributes": intent_request["requestAttributes"]
        if "requestAttributes" in intent_request
        else None,
    }


def delegate(session_attributes, intent_name, slots, message=None):
    return {
        "sessionState": {
            "sessionAttributes": session_attributes,
            "dialogAction": {"type": "Delegate"},
            "intent": {"name": intent_name, "slots": slots},
        },
        "message": message,
    }


def build_response_card(title, subtitle, imageUrl, options):
    buttons = None
    if options is not None:
        buttons = []
        for i in range(min(5, len(options))):
            buttons.append(options[i])

    return {
        "contentType": "ImageResponseCard",
        "content": "一つ選択してください",
        "imageResponseCard": {
            "title": title,
            "subtitle": subtitle,
            "imageUrl": imageUrl,
            "buttons": buttons,
        },
    }


def build_options(slot):
    if slot == "ChapterCode":
        return [
            {"text": "A章 消化器", "value": "A"},
            {"text": "B章 肝胆膵", "value": "B"},
            {"text": "C章 循環器", "value": "C"},
        ]
    elif slot == "QuestionNum":
        return [
            {"text": "3問", "value": 3},
            {"text": "5問", "value": 5},
            {"text": "7問", "value": 7},
        ]
    elif slot == "Confirmation":
        return [
            {"text": "もちろん!", "value": "Start QuizBot"},
            {"text": "忙しくて。。。", "value": "いいえ"},
        ]
    elif slot == "ResultConfirmation":
        return [
            {
                "text": "ううん...",
                "value": "True",
            },
            {"text": "ちょ、やめ", "value": "False"},
        ]
    else:
        return [{"text": "うん!!", "value": "はい"}, {"text": "ちがう！！", "value": "いいえ"}]


def build_validation_result(is_valid, violated_slot, message_content):
    return {
        "isValid": is_valid,
        "violatedSlot": violated_slot,
        "message": {"contentType": "PlainText", "content": message_content},
    }


def validate_chapter_value(chapter_code, question_num):
    valid_chapters = ["A", "B", "C"]
    valid_question_num = ["3", "5", "7"]
    print(f"chapter: {chapter_code}, max_question: {question_num}")
    if not chapter_code:
        return build_validation_result(False, "ChapterCode", "Chapterを選んでください")

    if chapter_code.upper() not in valid_chapters:
        return build_validation_result(
            False,
            "ChapterCode",
            "選択可能なChapterは {} のみとなっています。".format(", ".join(valid_chapters)),
        )
    if not question_num:
        return build_validation_result(False, "QuestionNum", "何問出題しますか？")

    if question_num.lower() not in valid_question_num:
        return build_validation_result(
            False,
            "QuestionNum",
            "選択可能な出題数は {} のみとなっています。".format(", ".join(valid_question_num)),
        )

    return build_validation_result(True, None, None)


def validate_answer_value(answer, kind):
    print(f"asnwer: {answer}, kind: {kind}")
    valid_answers_bool = ["はい", "いいえ"]

    if not answer:
        return build_validation_result(False, "Answer", "有効な回答ではありません。")

    if kind == "ChoiceBool":
        if answer not in valid_answers_bool:
            return build_validation_result(
                False,
                "Answer",
                "選択可能な回答は「{}」のみとなっています。".format(" , ".join(valid_answers_bool)),
            )

    return build_validation_result(True, None, None)


# chapter_code, question_num
def check_chapter(intent_request):
    slots = get_slots(intent_request)
    print(slots)
    chapter_code = get_slot(intent_request, "ChapterCode")
    question_num = get_slot(intent_request, "QuestionNum")
    source = intent_request["invocationSource"]
    output_session_attributes = get_session_attributes(intent_request)
    user_name = "匿名"
    if try_ex(lambda: output_session_attributes["userInfo"]) is not None:
        user_name = output_session_attributes["userInfo"]
    else:
        output_session_attributes["userInfo"] = user_name

    chapter_info = json.loads(
        try_ex(lambda: output_session_attributes["chapterInfo"]) or "{}"
    )
    print(chapter_info)
    print(source)
    if source == "DialogCodeHook":
        print("case 0(check_chapter)")
        validation_result = validate_chapter_value(chapter_code, question_num)
        print("validation_result: {}".format(validation_result))
        if not validation_result["isValid"]:
            print("case 1(check_chapter)")
            slots[validation_result["violatedSlot"]] = None
            response = elicit_slot(
                intent_request,
                output_session_attributes,
                intent_request["sessionState"]["intent"]["name"],
                slots,
                validation_result["violatedSlot"],
                [validation_result["message"]],
                build_response_card(
                    "{}を選んでください。".format(validation_result["violatedSlot"]),
                    "以下から選んでください",
                    None,
                    build_options(validation_result["violatedSlot"]),
                ),
            )
            print(response)
            return response
        response = confirm_intent(
            intent_request,
            output_session_attributes,
            intent_request["sessionState"]["intent"]["name"],
            slots,
            [
                {
                    "contentType": "PlainText",
                    "content": "{}章から{}問出題しますがよろしいですか？ {}さん".format(
                        chapter_code, question_num, user_name
                    ),
                }
            ],
            build_response_card(
                "最終確認",
                "確認です",
                None,
                build_options(validation_result["violatedSlot"]),
            ),
        )
        print(response)
        return response
    elif source == "FulfillmentCodeHook":
        chapter_info = {"chapter_code": chapter_code, "question_num": question_num}
        output_session_attributes["chapterInfo"] = json.dumps(chapter_info)
        print(output_session_attributes["chapterInfo"])
        response = confirm_intent(
            intent_request,
            output_session_attributes,
            intent_request["sessionState"]["intent"]["name"],
            slots,
            [
                {
                    "contentType": "CustomPayload",
                    "content": f"""準備は良いですか！  
                ***{user_name}***さん""",
                }
            ],
            build_response_card(
                "タイトル",
                f"準備はOK??? {user_name}さん",
                "https://media.tenor.com/3AtT96QV6AUAAAAC/let-it-begin-hamster.gif",
                build_options("Confirmation"),
            ),
        )
        print(response)
        return response


def format_question(content, title, subtitle, imageUrl, options):
    buttons = None
    if options is not None:
        buttons = []
        for i in range(min(5, len(options))):
            buttons.append(options[i])

    return {
        "contentType": "ImageResponseCard",
        "content": content,
        "imageResponseCard": {
            "title": title,
            "subtitle": subtitle,
            "imageUrl": imageUrl,
            "buttons": buttons,
        },
    }


def build_question_card(quiz, subtitle, current_num):
    quiz_type = quiz["kind"]
    quiz_text = quiz["q"]
    question_card = ""
    print(quiz_type, quiz_text)
    if quiz_type == "ChoiceBool":
        return format_question(
            f"第{current_num + 1}問：{quiz_text}",
            f"第{current_num + 1}問：{quiz_text}",
            subtitle,
            None,
            build_options("ChoiceBool"),
        )
    elif quiz_type == "Image":
        return format_question(
            f"第{current_num + 1}問：{quiz_text}",
            f"第{current_num + 1}問：{quiz_text}",
            subtitle,
            quiz["image"],
            None,
        )
    elif quiz_type == "Desc":
        return format_question(
            f"第{current_num + 1}問：{quiz_text}",
            f"第{current_num + 1}問：{quiz_text}",
            subtitle,
            None,
            None,
        )
    return question_card


def fetch_quiz_set(chapter_code, question_num):
    table_name = os.environ.get("DYNAMODB_TABLE", "QuizTable")
    region = os.environ.get("REGION_NAME", "us-east-1")

    quiz_table = boto3.resource("dynamodb", region_name=region)
    table = quiz_table.Table(table_name)

    response = table.query(KeyConditionExpression=Key("chapter_code").eq(chapter_code))

    print(":::::==>>>", response)

    print("{}章から{}問取得する".format(chapter_code, question_num))
    quiz_sets = response["Items"]
    random.shuffle(quiz_sets)
    quiz_list = json.loads(json.dumps(quiz_sets, default=decimal_default_proc))[
        : int(question_num)
    ]
    quiz_id_list = [str(d.get("id")) for d in quiz_list]
    return quiz_id_list


def set_quiz(chapter_code, q_id_list, current_num):
    table_name = os.environ.get("DYNAMODB_TABLE", "QuizTable")
    region = os.environ.get("REGION_NAME", "us-east-1")

    quiz_table = boto3.resource("dynamodb", region_name=region)
    table = quiz_table.Table(table_name)

    response = table.query(
        KeyConditionExpression=Key("chapter_code").eq(chapter_code)
        & Key("id").eq(int(q_id_list[current_num]))
    )
    print(":::::==>>>", response["Items"])
    return json.loads(json.dumps(response["Items"], default=decimal_default_proc))[0]


def update_exam_state_info(exam_state_info, quiz, current_num, result_value):
    # {"is_finished": boolean, current_num: number , max_num: number ,"results": [{"id": 1, "result": "correct"}, {"id": 2, "result": "incorrect"}]}
    if quiz is not None or current_num is not None or result_value is not None:
        exam_state_info["results"].append({"id": quiz["id"], "result": result_value})
        exam_state_info["current_num"] = current_num + 1
    else:
        exam_state_info["is_finished"] = True
    return exam_state_info


def judge_answer(quiz, answer, exam_state_info, current_num):
    # 判定結果ごとにexam_state_infoのupdate, messageの雛形とさいしんのexam_stateを返す
    # あっていたら「正解」間違ってたら「残念」と返答 exam_state_infoを更新
    print("解答", quiz["a"])
    print("回答", answer)
    print(exam_state_info)
    if answer in quiz["a"]:
        new_state = update_exam_state_info(
            exam_state_info, quiz, current_num, "correct"
        )
        output_message = f"""正解！！！  
        コメント： {quiz['comment']}"""
        return [new_state, output_message]
    elif answer in quiz["secondary_a"]:
        new_state = update_exam_state_info(
            exam_state_info, quiz, current_num, "incorrect"
        )
        output_message = f"""うーん いい線いっているけど不正解！　正解は ***{quiz["a"][0]}*** ね。
        コメント：{quiz['comment']}
        """
        return [new_state, output_message]
    else:
        new_state = update_exam_state_info(
            exam_state_info, quiz, current_num, "incorrect"
        )
        output_message = f"""残念....  正解は ***{quiz["a"][0]}*** ね。
        コメント： {quiz['comment']}"""
        return [new_state, output_message]


# is_canceled, is_displayed_results
def start_quiz(intent_request):
    is_canceled = True if get_slot(intent_request, "IsCanceled") == "True" else False
    is_displayed_results = (
        True if get_slot(intent_request, "IsDisplayedResults") == "True" else False
    )
    answer = get_slot(intent_request, "Answer")

    slots = get_slots(intent_request)
    output_session_attributes = get_session_attributes(intent_request)
    chapter_info = json.loads(
        try_ex(lambda: output_session_attributes["chapterInfo"]) or "{}"
    )

    if chapter_info == {}:
        return elicit_intent(
            intent_request,
            output_session_attributes,
            [
                {
                    "contentType": "PlainText",
                    "content": "章情報が取得できませんでした！もう一度試してください",
                }
            ],
            None,
        )

    chapter_code = chapter_info["chapter_code"]
    question_num = chapter_info["question_num"]

    user_name = try_ex(lambda: output_session_attributes["userInfo"]) or "匿名"
    # {"is_finished": boolean, current_num: number , max_num: number ,"results": [{"id": 1, "result": "correct"}, {"id": 2, "result": "incorrect"}]}
    exam_state_info = json.loads(
        try_ex(lambda: output_session_attributes["examState"])
        or json.dumps(
            {
                "is_finished": False,
                "max_num": question_num,
                "current_num": 0,
                "results": [],
                "q_list": [],
            }
        )
    )
    is_finished = exam_state_info["is_finished"]
    current_num = exam_state_info["current_num"]
    results_history_list = exam_state_info["results"]
    q_id_list = exam_state_info["q_list"]

    # キャンセル時の対応
    print("is_finished:", is_finished)

    # 結果発表時の対応
    if is_finished is True and is_displayed_results is False:
        print("結果を非表示で終了")
        clear_session_attributes(intent_request)
        return close(
            intent_request,
            {},
            "Fulfilled",
            [
                {"contentType": "PlainText", "content": "そうだよね。。。おつかれ！じゃあまたね！👋"},
            ],
        )
    elif is_finished is True and is_displayed_results is True:
        max_question = int(question_num)
        correct_q_count = len(
            list(
                filter(
                    lambda res: res["result"] == "correct", exam_state_info["results"]
                )
            )
        )

        if correct_q_count == max_question:
            text = "すごい全問正解！！"
        elif correct_q_count == 0:
            text = "今回は残念。また挑戦してね"
        else:
            text = "おしい！"
        clear_session_attributes(intent_request)
        return close(
            intent_request,
            {},
            "Fulfilled",
            [
                {
                    "contentType": "CustomPayload",
                    "content": f"""{user_name}さんの結果... 
                {max_question}問中.. {correct_q_count}問正解！！
                {text}
                """,
                },
                {"contentType": "PlainText", "content": "じゃあまたね！👋"},
            ],
        )

    source = intent_request["invocationSource"]
    if source == "DialogCodeHook":
        if is_canceled is True:
            print("終了")
        if is_finished is not True:
            if answer is not None:
                # answerのバリデーション処理
                q_item = set_quiz(chapter_code, q_id_list, current_num)
                validation_result = validate_answer_value(answer, q_item["kind"])
                if not validation_result["isValid"]:
                    print("answerのバリデーション処理", validation_result)
                    slots[validation_result["violatedSlot"]] = None
                    response = elicit_slot(
                        intent_request,
                        output_session_attributes,
                        intent_request["sessionState"]["intent"]["name"],
                        slots,
                        validation_result["violatedSlot"],
                        [
                            {
                                "contentType": "PlainText",
                                "content": f'{validation_result["message"]["content"]}',
                            }
                        ],
                        build_question_card(
                            q_item,
                            validation_result["message"]["content"],
                            current_num,
                        ),
                    )
                    return response

                # 判定処理（結果メッセージ+解説メッセージを受け取り、stateを更新している）
                [exam_state_info, message] = judge_answer(
                    q_item, answer, exam_state_info, current_num
                )
                print(exam_state_info, message)
                # slot(Answer)を空に、current_num更新してelicit_slot
                output_session_attributes["examState"] = json.dumps(exam_state_info)

                if (current_num + 1) < int(question_num):
                    # 次の問題があれば問題を作成する
                    slots["Answer"] = None
                    current_num += 1
                    q_item = set_quiz(chapter_code, q_id_list, current_num)
                    response = elicit_slot(
                        intent_request,
                        output_session_attributes,
                        intent_request["sessionState"]["intent"]["name"],
                        slots,
                        "Answer",
                        [
                            {"contentType": "CustomPayload", "content": f"{message}"},
                            {
                                "contentType": "CustomPayload",
                                "content": f"第{current_num + 1}問：{q_item['q']}",
                            },
                        ],
                        build_question_card(
                            q_item,
                            f"ヒント：{q_item['hint']}",
                            current_num,
                        ),
                    )
                else:
                    # 次の問題なければ
                    new_state = update_exam_state_info(
                        exam_state_info, None, None, None
                    )
                    output_session_attributes["examState"] = json.dumps(exam_state_info)
                    response = elicit_slot(
                        intent_request,
                        output_session_attributes,
                        intent_request["sessionState"]["intent"]["name"],
                        slots,
                        "IsDisplayedResults",
                        [
                            {"contentType": "CustomPayload", "content": f"{message}"},
                            {
                                "contentType": "CustomPayload",
                                "content": f"""お疲れさまでした！{user_name}さん!!
                        結果を表示しますか？""",
                            },
                        ],
                        build_response_card(
                            "以下から選んでください",
                            "以下から選んでください",
                            None,
                            build_options("ResultConfirmation"),
                        ),
                    )
                return response
            if len(q_id_list) == 0:
                q_id_list = fetch_quiz_set(chapter_code, question_num)
                exam_state_info = json.dumps(
                    {
                        "is_finished": False,
                        "max_num": question_num,
                        "current_num": 0,
                        "results": [],
                        "q_list": q_id_list,
                    }
                )

                output_session_attributes["examState"] = exam_state_info
            q_item = set_quiz(chapter_code, q_id_list, current_num)
            print("出題", q_item)
            # 出題カード作成
            response = elicit_slot(
                intent_request,
                output_session_attributes,
                intent_request["sessionState"]["intent"]["name"],
                slots,
                "Answer",
                [
                    {"contentType": "PlainText", "content": f"{chapter_code}章からの出題"},
                    {
                        "contentType": "CustomPayload",
                        "content": f"第{current_num + 1}問：{q_item['q']}",
                    },
                ],
                build_question_card(
                    q_item,
                    f"ヒント：{q_item['hint']}",
                    current_num,
                ),
            )
            return response

        return delegate(
            output_session_attributes,
            intent_request["sessionState"]["intent"]["name"],
            slots,
        )


def welcome(intent_request):
    slots = get_slots(intent_request)
    user_name = get_slot(intent_request, "UserName")
    output_session_attributes = get_session_attributes(intent_request)

    if user_name is not None:
        print("elicit intent(Welcome)", user_name)
        output_session_attributes["userInfo"] = user_name

        return close(
            intent_request,
            output_session_attributes,
            "Fulfilled",
            [
                {
                    "contentType": "CustomPayload",
                    "content": f"こんにちは！ ***{user_name}***さん。 <br /> 今日はどうなさいましたか？",
                }
            ],
        )

    else:
        print("Delegate!!(welcome)")
        return delegate(
            output_session_attributes,
            intent_request["sessionState"]["intent"]["name"],
            slots,
        )


def dispatch(intent_request):
    logger.debug(
        "dispatch sessionId={}, intentName={}".format(
            intent_request["sessionId"],
            intent_request["sessionState"]["intent"]["name"],
        )
    )

    intent_name = intent_request["sessionState"]["intent"]["name"]

    # Dispatch to your bot's intent handlers
    if intent_name == "CheckChapter":
        return check_chapter(intent_request)
    elif intent_name == "StartQuiz":
        return start_quiz(intent_request)
    elif intent_name == "Welcome":
        return welcome(intent_request)
    # elif intent_name == "DisplayRusult":
    #     return display_result(intent_request)
    raise Exception("Intent with name " + intent_name + " not supported")


def lambda_handler(event, context):
    os.environ["TZ"] = "Asia/Tokyo"
    time.tzset()
    logger.debug("event.bot.name={}".format(event["bot"]["name"]))
    logger.debug("event: {}".format(event))

    return dispatch(event)


# # メモ
# 1 .elicit_intentモードだと、カードは使えない
# 2 .二度続けてメッセージを送る場合は、
# a)初期応答(lexコンソールから設定)→slotプロンプト(lexコンソールから設定)
# b)確認応答（lexコンソールから設定）→ confirm_intent(lambdaから)
# c) messagesのリストに複数のcontentを追加すればよし
# 3. カスタムslot タイプのBooleanも文字列として帰ってくるので注意

# TODO: 1 途中離脱の方法(「やめる」と言ったら、セッション情報削除してclose)
