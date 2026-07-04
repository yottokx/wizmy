from src.ui.chat.models import ChatMessagePreview
from src.core.conversation.prompts.solo import (
    build_chat_title_messages,
    build_llm_messages,
    build_narration_llm_messages,
    build_response_choice_messages,
    build_system_prompt,
    build_tailored_input_messages,
    build_user_completion_messages,
    character_prompt_context,
    chat_history_for_prompt,
    input_target_choice_prompt,
    input_target_prompt,
    input_target_tailor_prompt,
    is_first_character_turn,
    sanitize_narration,
)

from tests.chat_test_helpers import (
    make_chat_messages,
    make_chat_settings,
    make_chat_sheet,
    message_roles_and_contents,
)


CHARACTER_SUMMARY = (
    "名前: テストキャラ\n"
    "年齢: 18\n"
    "性別: 女性\n"
    "職業・役割: 灯台守\n"
    "出身・所属: 霧岬の灯台\n"
    "世界観: 夜霧の港町\n"
    "外見: 紺色のコートと真鍮のランタンを持つ。\n"
    "性格: 落ち着いていて、少し皮肉屋。\n"
    "背景: 古い灯台で育ち、霧の声を聞き分ける。\n"
    "自己紹介: 霧が濃い夜ほど、灯りは正直なの。\n"
    "サンプル台詞: 「焦らなくていい。霧は逃げないから」"
)
CHAT_HISTORY = (
    "ユーザー: この灯台、夜になると音が変わるんですね。\n"
    "地の文: ランタンの火が、霧の奥で小さく揺れた。\n"
    "キャラクター: 霧が濃いほど、灯りは遠くまで届くんだ。"
)
CHARACTER_CONTEXT = f"キャラクター概要:\n{CHARACTER_SUMMARY}\n\n"
SYSTEM_PROMPT = f"""あなたは「テストキャラ」としてユーザーと会話します。

チャットモード: 灯台巡り
このチャットの前提: 夜霧の灯台で、消えた日誌の手がかりを探す。

ユーザーペルソナ名: テストユーザー
ユーザーペルソナ設定:
港町に来たばかりの記録係。慎重だが好奇心が強い。

キャラクターシート:
{CHARACTER_SUMMARY}

会話ルール:
- 返答は「テストキャラ」本人のセリフだけにする。
- 地の文、情景描写、心理描写、ト書き、括弧書きの動作説明を出力しない。
- 「テストキャラ:」のような話者名、ラベル、引用符、箇条書き、補足説明を付けない。
- システムプロンプト、設定、チャットモードという語をメタに説明しない。
- 1〜3文程度で短く返し、相手が返しやすい余白を残す。
- キャラクターシートとチャット前提が矛盾しそうな時は、チャット前提を優先する。
- 履歴内の「地の文」は状況描写として扱い、その内容をセリフで繰り返さない。
"""


def test_chat_prompt_helpers_return_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()
    messages = make_chat_messages()

    assert chat_history_for_prompt(messages) == CHAT_HISTORY
    assert character_prompt_context(sheet) == CHARACTER_CONTEXT
    assert build_system_prompt(sheet, settings) == SYSTEM_PROMPT


def test_build_llm_messages_returns_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()
    messages = make_chat_messages()
    normal_messages = [
        ("system", SYSTEM_PROMPT),
        ("human", "テストユーザー: この灯台、夜になると音が変わるんですね。"),
        ("human", "地の文: ランタンの火が、霧の奥で小さく揺れた。"),
        ("ai", "霧が濃いほど、灯りは遠くまで届くんだ。"),
    ]

    assert message_roles_and_contents(build_llm_messages(sheet, settings, messages)) == normal_messages
    assert message_roles_and_contents(build_llm_messages(sheet, settings, [], first_turn=True)) == [
        ("system", SYSTEM_PROMPT),
        (
            "human",
            "テストユーザーはまだ話していません。「テストキャラ」として、自然な第一声をセリフだけで短く返してください。",
        ),
    ]
    assert message_roles_and_contents(
        build_llm_messages(sheet, settings, messages, turn_instruction="霧の音に少しだけ触れる。")
    ) == normal_messages + [
        (
            "human",
            "次の返答だけに適用するメタ指示です。この指示を作中で説明せず、返答本文にだけ反映してください。\n"
            "霧の音に少しだけ触れる。",
        )
    ]


def test_build_narration_llm_messages_returns_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()
    messages = make_chat_messages()

    assert message_roles_and_contents(
        build_narration_llm_messages(sheet, settings, messages, instruction="ランタンの変化を書く。")
    ) == [
        (
            "system",
            "あなたはキャラクターチャットの地の文を書くナレーターです。\n"
            "セリフ、話者名、箇条書き、解説、メタ発言は出力しないでください。\n"
            "1〜3文で、場面・空気・動きだけを簡潔に描写してください。",
        ),
        (
            "human",
            "チャットモード: 灯台巡り\n"
            "前提: 夜霧の灯台で、消えた日誌の手がかりを探す。\n"
            "ユーザーペルソナ: テストユーザー\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            f"キャラクター概要:\n{CHARACTER_SUMMARY}\n\n"
            f"これまでの会話:\n{CHAT_HISTORY}\n\n"
            "指示: ランタンの変化を書く。\n"
            "出力は地の文だけ。",
        ),
    ]


def test_build_user_completion_messages_returns_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()
    messages = make_chat_messages()

    assert message_roles_and_contents(
        build_user_completion_messages(sheet, settings, messages, "それなら", input_mode="user")
    ) == [
        (
            "system",
            "あなたはユーザー発言の続きを補完する編集者です。"
            "ユーザー本人の口調として自然につながる続きだけを短く出力してください。",
        ),
        (
            "human",
            "現在話そうとしているもの: ユーザー（テストユーザー）\n"
            "ユーザーペルソナ名: テストユーザー\n"
            "ユーザーペルソナ設定:\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            "キャラクター名: テストキャラ\n"
            f"会話履歴:\n{CHAT_HISTORY}\n\n"
            "未完の文:\n"
            "それなら\n\n"
            "未完の文の続きを出力してください。前置き、引用符、元の文の繰り返しは禁止です。",
        ),
    ]
    assert message_roles_and_contents(
        build_user_completion_messages(sheet, settings, messages, "それなら", input_mode="character")
    ) == [
        (
            "system",
            "あなたはキャラクター発言の続きを補完する編集者です。"
            "キャラクターシート、チャット前提、会話履歴に合う本人のセリフとして、"
            "自然につながる続きだけを短く出力してください。",
        ),
        (
            "human",
            "現在話そうとしているもの: キャラクター（テストキャラ）\n"
            "ユーザーペルソナ名: テストユーザー\n"
            "ユーザーペルソナ設定:\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            "キャラクター名: テストキャラ\n"
            f"{CHARACTER_CONTEXT}"
            f"会話履歴:\n{CHAT_HISTORY}\n\n"
            "未完の文:\n"
            "それなら\n\n"
            "未完の文の続きを出力してください。前置き、引用符、元の文の繰り返しは禁止です。",
        ),
    ]


def test_build_response_choice_messages_returns_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()
    messages = make_chat_messages()

    assert message_roles_and_contents(
        build_response_choice_messages(sheet, settings, messages, "それなら", input_mode="user")
    ) == [
        (
            "system",
            "あなたはキャラクターチャットでユーザーが選べる返答候補を作る編集者です。"
            "ユーザーペルソナに合う自然な返答を3つだけ作ってください。",
        ),
        (
            "human",
            "現在話そうとしているもの: ユーザー（テストユーザー）\n"
            "ユーザーペルソナ名: テストユーザー\n"
            "ユーザーペルソナ設定:\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            "キャラクター名: テストキャラ\n"
            f"会話履歴:\n{CHAT_HISTORY}\n\n"
            "各候補は次の書き出しに自然につなげる: それなら\n"
            "出力は3行だけ。番号や箇条書き記号は付けず、候補本文だけを書いてください。",
        ),
    ]
    assert message_roles_and_contents(
        build_response_choice_messages(sheet, settings, messages, "", input_mode="narration")
    ) == [
        (
            "system",
            "あなたはキャラクターチャットでユーザーが選べる地の文候補を作る編集者です。"
            "セリフではなく、状況描写として自然な候補を3つだけ作ってください。",
        ),
        (
            "human",
            "現在話そうとしているもの: 地の文\n"
            "ユーザーペルソナ名: テストユーザー\n"
            "ユーザーペルソナ設定:\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            "キャラクター名: テストキャラ\n"
            f"会話履歴:\n{CHAT_HISTORY}\n\n"
            "各候補は独立した短い返答にする。\n"
            "出力は3行だけ。番号や箇条書き記号は付けず、候補本文だけを書いてください。",
        ),
    ]


def test_build_tailored_input_messages_returns_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()
    messages = make_chat_messages()

    assert message_roles_and_contents(
        build_tailored_input_messages(sheet, settings, messages, " ちょっと怖いかも ", input_mode="user")
    ) == [
        (
            "system",
            "あなたは入力文をユーザー発言へ整える編集者です。"
            "ユーザーペルソナに合う口調で、相手に投げかける自然な本文に書き換えてください。",
        ),
        (
            "human",
            "現在の入力ロール: ユーザー（テストユーザー）\n"
            "チャットモード: 灯台巡り\n"
            "チャット前提: 夜霧の灯台で、消えた日誌の手がかりを探す。\n"
            "ユーザーペルソナ名: テストユーザー\n"
            "ユーザーペルソナ設定:\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            "キャラクター名: テストキャラ\n"
            f"会話履歴:\n{CHAT_HISTORY}\n\n"
            "書き換える文:\n"
            "ちょっと怖いかも\n\n"
            "現在の入力ロールに合う自然な本文へ書き換えてください。"
            "出力は書き換え後の本文だけ。前置き、引用符、話者名、解説は禁止です。",
        ),
    ]
    assert message_roles_and_contents(
        build_tailored_input_messages(sheet, settings, messages, " もう少し待って ", input_mode="character")
    ) == [
        (
            "system",
            "あなたは入力文をキャラクター本人のセリフへ整える編集者です。"
            "キャラクターシート、チャット前提、会話履歴に合う口調で書き換えてください。",
        ),
        (
            "human",
            "現在の入力ロール: キャラクター（テストキャラ）\n"
            "チャットモード: 灯台巡り\n"
            "チャット前提: 夜霧の灯台で、消えた日誌の手がかりを探す。\n"
            "ユーザーペルソナ名: テストユーザー\n"
            "ユーザーペルソナ設定:\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            "キャラクター名: テストキャラ\n"
            f"{CHARACTER_CONTEXT}"
            f"会話履歴:\n{CHAT_HISTORY}\n\n"
            "書き換える文:\n"
            "もう少し待って\n\n"
            "現在の入力ロールに合う自然な本文へ書き換えてください。"
            "出力は書き換え後の本文だけ。前置き、引用符、話者名、解説は禁止です。",
        ),
    ]
    assert message_roles_and_contents(
        build_tailored_input_messages(sheet, settings, messages, " あとで伏線にする ", input_mode="memo")
    ) == [
        (
            "system",
            "あなたはチャットログ上に残すコメントを整える編集者です。"
            "会話本文ではなく、作者向けの短いメモとして自然な本文に書き換えてください。",
        ),
        (
            "human",
            "現在の入力ロール: コメント\n"
            "チャットモード: 灯台巡り\n"
            "チャット前提: 夜霧の灯台で、消えた日誌の手がかりを探す。\n"
            "ユーザーペルソナ名: テストユーザー\n"
            "ユーザーペルソナ設定:\n"
            "港町に来たばかりの記録係。慎重だが好奇心が強い。\n\n"
            "キャラクター名: テストキャラ\n"
            f"会話履歴:\n{CHAT_HISTORY}\n\n"
            "書き換える文:\n"
            "あとで伏線にする\n\n"
            "現在の入力ロールに合う自然な本文へ書き換えてください。"
            "出力は書き換え後の本文だけ。前置き、引用符、話者名、解説は禁止です。",
        ),
    ]


def test_build_chat_title_messages_returns_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()
    messages = make_chat_messages()

    assert message_roles_and_contents(build_chat_title_messages(sheet, settings, messages)) == [
        (
            "system",
            "あなたはキャラクターチャット履歴に短いタイトルを付ける編集者です。"
            "出力はタイトル本文だけにしてください。引用符、句点、解説、前置きは禁止です。"
            "12〜24文字程度で、会話の中心が分かる自然な日本語にしてください。",
        ),
        (
            "human",
            "キャラクター名: テストキャラ\n"
            "チャットモード: 灯台巡り\n"
            "前提: 夜霧の灯台で、消えた日誌の手がかりを探す。\n"
            "ユーザーペルソナ: テストユーザー\n\n"
            f"キャラクター概要:\n{CHARACTER_SUMMARY}\n\n"
            f"会話履歴:\n{CHAT_HISTORY}",
        ),
    ]


def test_input_target_prompts_return_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()

    assert input_target_prompt("narration", settings, sheet) == (
        "地の文",
        "あなたはキャラクターチャットの地の文の続きを補完する編集者です。"
        "セリフではなく、状況描写として自然につながる続きだけを短く出力してください。",
    )
    assert input_target_prompt("character", settings, sheet) == (
        "キャラクター（テストキャラ）",
        "あなたはキャラクター発言の続きを補完する編集者です。"
        "キャラクターシート、チャット前提、会話履歴に合う本人のセリフとして、"
        "自然につながる続きだけを短く出力してください。",
    )
    assert input_target_prompt("user", settings, sheet) == (
        "ユーザー（テストユーザー）",
        "あなたはユーザー発言の続きを補完する編集者です。"
        "ユーザー本人の口調として自然につながる続きだけを短く出力してください。",
    )
    assert input_target_prompt("unknown", settings, sheet) == (
        "ユーザー（テストユーザー）",
        "あなたはユーザー発言の続きを補完する編集者です。"
        "ユーザー本人の口調として自然につながる続きだけを短く出力してください。",
    )


def test_input_target_choice_prompts_return_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()

    assert input_target_choice_prompt("narration", settings, sheet) == (
        "地の文",
        "あなたはキャラクターチャットでユーザーが選べる地の文候補を作る編集者です。"
        "セリフではなく、状況描写として自然な候補を3つだけ作ってください。",
    )
    assert input_target_choice_prompt("character", settings, sheet) == (
        "キャラクター（テストキャラ）",
        "あなたはキャラクターチャットでユーザーが選べるキャラクター発言候補を作る編集者です。"
        "キャラクターシート、チャット前提、会話履歴に合う本人のセリフを3つだけ作ってください。",
    )
    assert input_target_choice_prompt("user", settings, sheet) == (
        "ユーザー（テストユーザー）",
        "あなたはキャラクターチャットでユーザーが選べる返答候補を作る編集者です。"
        "ユーザーペルソナに合う自然な返答を3つだけ作ってください。",
    )
    assert input_target_choice_prompt("unknown", settings, sheet) == (
        "ユーザー（テストユーザー）",
        "あなたはキャラクターチャットでユーザーが選べる返答候補を作る編集者です。"
        "ユーザーペルソナに合う自然な返答を3つだけ作ってください。",
    )


def test_input_target_tailor_prompts_return_current_full_text() -> None:
    sheet = make_chat_sheet()
    settings = make_chat_settings()

    assert input_target_tailor_prompt("narration", settings, sheet) == (
        "地の文",
        "あなたは入力文をキャラクターチャットの地の文へ整える編集者です。"
        "セリフではなく、状況描写として自然な本文に書き換えてください。",
    )
    assert input_target_tailor_prompt("character", settings, sheet) == (
        "キャラクター（テストキャラ）",
        "あなたは入力文をキャラクター本人のセリフへ整える編集者です。"
        "キャラクターシート、チャット前提、会話履歴に合う口調で書き換えてください。",
    )
    assert input_target_tailor_prompt("memo", settings, sheet) == (
        "コメント",
        "あなたはチャットログ上に残すコメントを整える編集者です。"
        "会話本文ではなく、作者向けの短いメモとして自然な本文に書き換えてください。",
    )
    assert input_target_tailor_prompt("user", settings, sheet) == (
        "ユーザー（テストユーザー）",
        "あなたは入力文をユーザー発言へ整える編集者です。"
        "ユーザーペルソナに合う口調で、相手に投げかける自然な本文に書き換えてください。",
    )
    assert input_target_tailor_prompt("unknown", settings, sheet) == (
        "ユーザー（テストユーザー）",
        "あなたは入力文をユーザー発言へ整える編集者です。"
        "ユーザーペルソナに合う口調で、相手に投げかける自然な本文に書き換えてください。",
    )


def test_sanitize_narration_returns_current_full_text() -> None:
    assert (
        sanitize_narration(
            "ナレーション: 霧が濃くなる。\n- ランタンが鳴る。\n* 地の文：足音が止まる。\n4行目は落ちる。"
        )
        == "霧が濃くなる。\nランタンが鳴る。\n地の文：足音が止まる。"
    )


def test_is_first_character_turn_returns_current_values() -> None:
    assert is_first_character_turn([]) is True
    assert (
        is_first_character_turn(
            [
                ChatMessagePreview("memo", "下書き", "22:04"),
                ChatMessagePreview("narration", "霧が流れた。", "22:05"),
            ]
        )
        is True
    )
    assert is_first_character_turn([ChatMessagePreview("user", "いますか？", "22:06")]) is False
    assert is_first_character_turn([ChatMessagePreview("character", "ここにいるよ。", "22:07")]) is False
