from src.core.conversation.history import format_group_history
from src.ui.pages.group_chat import (
    _build_group_character_messages,
    _build_group_guest_messages,
    _build_group_input_completion_messages,
    _build_group_narration_messages,
    _build_group_response_choice_messages,
    _build_group_system_prompt,
    _build_group_tailored_input_messages,
    _build_group_title_messages,
    _format_group_participant_overview,
    _format_group_relationship_section,
    _group_input_target_context,
    _group_user_persona_context,
)

from tests.group_chat_test_helpers import (
    make_group_chat,
    make_group_messages,
    make_group_settings,
    message_roles_and_contents,
)


AKARI_SUMMARY = (
    "名前: 灯里\n"
    "年齢: 17\n"
    "性別: 女性\n"
    "職業・役割: 資料整理係\n"
    "出身・所属: 星見図書館\n"
    "世界観: 遠い星の図書館\n"
    "外見: 青いケープと銀の栞を身につけている。\n"
    "性格: 穏やかで観察好き。\n"
    "背景: 古い星図を守っている。\n"
    "自己紹介: 灯りを消さずに待っています。\n"
    "サンプル台詞: 「この棚、まだ眠っているみたい」"
)
MINATO_SUMMARY = (
    "名前: 湊\n"
    "年齢: 19\n"
    "性別: 男性\n"
    "職業・役割: 修理屋\n"
    "出身・所属: 時計塔通り\n"
    "世界観: 遠い星の図書館\n"
    "外見: 工具鞄を肩にかけている。\n"
    "性格: 軽口を叩くが手元は丁寧。\n"
    "背景: 壊れた天球儀を直しに来た。\n"
    "自己紹介: 直せるものなら任せてよ。\n"
    "サンプル台詞: 「歯車の声が少しずれてる」"
)
AKARI_COMPACT = (
    "名前: 灯里 年齢: 17 性別: 女性 職業・役割: 資料整理係 出身・所属: 星見図書館 世界観: 遠い星の図書館 "
    "外見: 青いケープと銀の栞を身につけている。 性格: 穏やかで観察好き。 背景: 古い星図を守っている。 "
    "自己紹介: 灯りを消さずに待っています。 サンプル台詞: 「この棚、まだ眠っているみたい」"
)
MINATO_COMPACT = (
    "名前: 湊 年齢: 19 性別: 男性 職業・役割: 修理屋 出身・所属: 時計塔通り 世界観: 遠い星の図書館 "
    "外見: 工具鞄を肩にかけている。 性格: 軽口を叩くが手元は丁寧。 背景: 壊れた天球儀を直しに来た。 "
    "自己紹介: 直せるものなら任せてよ。 サンプル台詞: 「歯車の声が少しずれてる」"
)
USER_CONTEXT = "記録係として同行する旅人。\nこの世界に来た理由: 古い招待状を受け取った。"
HISTORY = (
    "ソラ(@Sora): この星図、昨日と線が違う気がします。\n"
    "灯里(@Akari): 星図は夜ごとに少しだけ息をするんです。\n"
    "巡回司書【ゲスト】: 閉館の鐘まで、あと少しですよ。\n"
    "地の文: 窓辺の天球儀が、かすかに青く光った。"
)
PARTICIPANT_OVERVIEW = (
    f"- @Akari / 灯里: {AKARI_COMPACT}\n- @Minato / 湊: {MINATO_COMPACT}\n- @Sora / ソラ: {USER_CONTEXT}"
)
RELATIONSHIP_SECTION = (
    "関係性:\n"
    "- 灯里 (@Akari) ↔ 湊 (@Minato): 古い星図の修復を一緒に進めている。\n"
    "- 灯里 (@Akari) ↔ ソラ (@Sora): 灯里はソラを新米の記録係として見守っている。\n\n"
)
SYSTEM_PROMPT = (
    "あなたはグループチャットの参加キャラクターを演じます。\n"
    "指定された次の発言者だけとして発言してください。話者名、ハンドル、引用符、前置き、解説は出力しないでください。\n"
    "特別な理由がない限り、キャラクター発言にメンションは含めないでください。\n\n"
    "発言は通常の1対1チャットと同じくらい短くしてください。1〜3文程度で短く返し、相手が返しやすい余白を残してください。\n\n"
    "グループ名: 星見図書館の夜会\n"
    "世界観:\n"
    "星が本の背表紙に宿る静かな図書館。\n\n"
    "ユーザー:\n"
    f"@Sora / ソラ\n{USER_CONTEXT}\n\n"
    "参加キャラクター:\n"
    f"- @Akari / 灯里: {AKARI_COMPACT}\n"
    f"- @Minato / 湊: {MINATO_COMPACT}\n\n"
    f"{RELATIONSHIP_SECTION}"
    "今回の発言者:\n"
    f"@Akari / 灯里\n{AKARI_SUMMARY}\n\n"
    "シチュエーション:\n"
    "星見図書館の夜更け。閲覧室に古い星図が広げられている。"
)


def test_group_prompt_helpers_return_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()

    assert format_group_history(make_group_messages()) == HISTORY
    assert _format_group_participant_overview(group, settings) == PARTICIPANT_OVERVIEW
    assert _group_user_persona_context(group.user_persona) == USER_CONTEXT
    assert _format_group_relationship_section(group, settings) == RELATIONSHIP_SECTION
    assert _group_input_target_context(group, "memo", None, tailor=True) == (
        "コメント",
        "あなたはグループチャットログ上に残すコメントを書き換える編集者です。会話本文ではなく、作者向けの短いメモとして自然な本文だけを出力してください。",
        "",
    )


def test_build_group_system_prompt_returns_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()

    prompt = _build_group_system_prompt(group, settings, group.members, group.members[0])

    assert prompt == SYSTEM_PROMPT


def test_build_group_character_messages_returns_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()
    messages = make_group_messages()

    result = _build_group_character_messages(
        group,
        settings,
        messages,
        group.members[0],
        turn_instruction="星図への驚きを少しだけ出す。",
    )

    assert message_roles_and_contents(result) == [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            f"会話履歴:\n{HISTORY}\n\n"
            "次の発言者は @Akari / 灯里 です。このキャラクターの自然な次の発言を、本文だけで返してください。"
            "通常チャットと同じくらい短く、1〜3文程度で相手が返しやすい余白を残してください。"
            "\n\n次の返答だけに適用するメタ指示です。この指示を作中で説明せず、返答本文にだけ反映してください。\n"
            "星図への驚きを少しだけ出す。",
        ),
    ]


def test_build_group_guest_messages_returns_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()
    messages = make_group_messages()

    result = _build_group_guest_messages(
        group,
        settings,
        messages,
        "guest:巡回司書",
        turn_instruction="閉館時間に触れる。",
    )

    assert message_roles_and_contents(result) == [
        (
            "system",
            "あなたはグループチャットの一時的なゲスト発言者を演じます。"
            "指定されたゲスト本人の自然な発言本文だけを出力してください。"
            "話者名、ハンドル、引用符、前置き、解説は出力しないでください。"
            "発言は短く、1〜3文程度で場面に自然につながる内容にしてください。",
        ),
        (
            "human",
            "グループ名: 星見図書館の夜会\n"
            "世界観:\n"
            "星が本の背表紙に宿る静かな図書館。\n\n"
            "シチュエーション:\n"
            "星見図書館の夜更け。閲覧室に古い星図が広げられている。\n\n"
            f"参加者:\n{PARTICIPANT_OVERVIEW}\n\n"
            f"{RELATIONSHIP_SECTION}"
            f"会話履歴:\n{HISTORY}\n\n"
            "今回のゲスト発言者: 巡回司書【ゲスト】\n"
            "このゲストの自然な次の発言を、本文だけで返してください。"
            "\n\n次の返答だけに適用するメタ指示です。この指示を作中で説明せず、返答本文にだけ反映してください。\n"
            "閉館時間に触れる。",
        ),
    ]


def test_build_group_narration_messages_returns_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()
    messages = make_group_messages()

    result = _build_group_narration_messages(group, settings, messages, instruction="星図の光を描写する。")

    assert message_roles_and_contents(result) == [
        (
            "system",
            "あなたはグループチャットの地の文を書くナレーターです。"
            "セリフ、話者名、箇条書き、解説、メタ発言は出力しないでください。"
            "1〜3文で、場面・空気・動きだけを簡潔に描写してください。",
        ),
        (
            "human",
            "グループ名: 星見図書館の夜会\n"
            "世界観:\n"
            "星が本の背表紙に宿る静かな図書館。\n\n"
            "シチュエーション:\n"
            "星見図書館の夜更け。閲覧室に古い星図が広げられている。\n\n"
            f"参加者:\n{PARTICIPANT_OVERVIEW}\n\n"
            f"{RELATIONSHIP_SECTION}"
            f"会話履歴:\n{HISTORY}\n\n"
            "指示: 星図の光を描写する。\n"
            "出力は地の文だけ。",
        ),
    ]


def test_build_group_input_completion_messages_returns_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()
    messages = make_group_messages()

    result = _build_group_input_completion_messages(
        group,
        settings,
        messages,
        "それなら",
        input_mode="character",
        speaker=group.members[0],
    )

    assert message_roles_and_contents(result) == [
        (
            "system",
            "あなたはキャラクター発言を続きを補完する編集者です。指定キャラクター本人の自然なセリフだけを短く出力してください。",
        ),
        (
            "human",
            "現在話そうとしているもの: キャラクター（灯里 / @Akari）\n"
            "グループ名: 星見図書館の夜会\n"
            "世界観:\n"
            "星が本の背表紙に宿る静かな図書館。\n"
            "シチュエーション:\n"
            "星見図書館の夜更け。閲覧室に古い星図が広げられている。\n\n"
            f"参加者:\n{PARTICIPANT_OVERVIEW}\n\n"
            f"{RELATIONSHIP_SECTION}"
            f"対象キャラクター:\n@Akari / 灯里\n{AKARI_SUMMARY}\n\n"
            f"会話履歴:\n{HISTORY}\n\n"
            "未完の文:\n"
            "それなら\n\n"
            "未完の文の続きを出力してください。前置き、引用符、元の文の繰り返しは禁止です。",
        ),
    ]


def test_build_group_tailored_input_messages_returns_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()
    messages = make_group_messages()

    result = _build_group_tailored_input_messages(
        group,
        settings,
        messages,
        "えっと、どうしよう",
        input_mode="guest",
        guest_name="巡回司書",
    )

    assert message_roles_and_contents(result) == [
        (
            "system",
            "あなたはゲスト発言を書き換える編集者です。指定されたゲスト本人の自然なセリフだけを短く出力してください。",
        ),
        (
            "human",
            "現在の入力ロール: ゲスト（巡回司書【ゲスト】）\n"
            "グループ名: 星見図書館の夜会\n"
            "世界観:\n"
            "星が本の背表紙に宿る静かな図書館。\n"
            "シチュエーション:\n"
            "星見図書館の夜更け。閲覧室に古い星図が広げられている。\n\n"
            f"参加者:\n{PARTICIPANT_OVERVIEW}\n\n"
            f"{RELATIONSHIP_SECTION}"
            "ゲスト発言者:\n"
            "巡回司書【ゲスト】\n\n"
            f"会話履歴:\n{HISTORY}\n\n"
            "書き換える文:\n"
            "えっと、どうしよう\n\n"
            "現在の入力ロールに合う自然な本文へ書き換えてください。"
            "出力は書き換え後の本文だけ。前置き、引用符、話者名、解説は禁止です。",
        ),
    ]


def test_build_group_response_choice_messages_returns_current_full_text() -> None:
    group = make_group_chat()
    settings = make_group_settings()
    messages = make_group_messages()

    result = _build_group_response_choice_messages(
        group,
        settings,
        messages,
        "それなら",
        input_mode="user",
    )

    assert message_roles_and_contents(result) == [
        (
            "system",
            "あなたはユーザー発言を候補を作る編集者です。ユーザー本人の口調として自然につながる本文だけを短く出力してください。",
        ),
        (
            "human",
            "現在話そうとしているもの: ユーザー（ソラ）\n"
            "グループ名: 星見図書館の夜会\n"
            "世界観:\n"
            "星が本の背表紙に宿る静かな図書館。\n"
            "シチュエーション:\n"
            "星見図書館の夜更け。閲覧室に古い星図が広げられている。\n\n"
            f"参加者:\n{PARTICIPANT_OVERVIEW}\n\n"
            f"{RELATIONSHIP_SECTION}"
            f"ユーザー設定:\n@Sora / ソラ\n{USER_CONTEXT}\n\n"
            f"会話履歴:\n{HISTORY}\n\n"
            "各候補は次の書き出しに自然につなげる: それなら\n"
            "出力は3行だけ。番号や箇条書き記号は付けず、候補本文だけを書いてください。",
        ),
    ]


def test_build_group_title_messages_returns_current_full_text() -> None:
    group = make_group_chat()
    messages = make_group_messages()

    result = _build_group_title_messages(group, messages)

    assert message_roles_and_contents(result) == [
        (
            "system",
            "あなたはグループチャット履歴に短いタイトルを付ける編集者です。"
            "出力はタイトル本文だけにしてください。引用符、句点、解説、前置きは禁止です。"
            "12〜24文字程度で、会話の中心が分かる自然な日本語にしてください。",
        ),
        (
            "human",
            "グループ名: 星見図書館の夜会\n"
            "世界観:\n"
            "星が本の背表紙に宿る静かな図書館。\n\n"
            f"{RELATIONSHIP_SECTION}"
            f"会話履歴:\n{HISTORY}",
        ),
    ]
