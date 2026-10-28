"""테스트용 가짜 kaikki 데이터 생성"""
import gzip, json, sys, os
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
en = [
 {"word":"ephemeral","lang":"English","lang_code":"en","pos":"adj",
  "etymology_text":"From Ancient Greek ἐφήμερος (ephḗmeros, “lasting only one day”).",
  "sounds":[{"ipa":"/ɪˈfɛm.əɹ.əl/","tags":["UK"]},{"ipa":"/əˈfɛm.ɚ.əl/"}],
  "senses":[{"glosses":["Lasting for a short period of time."],"tags":["figuratively"],
             "examples":[{"text":"Fame is ephemeral.","type":"example"},{"text":"A very long quotation "*30,"type":"quotation"}],
             "synonyms":[{"word":"transient"},{"word":"fleeting"}]},
            {"glosses":["Existing for only one day."],"antonyms":[{"word":"permanent"}]}],
  "translations":[{"lang":"Korean","lang_code":"ko","word":"덧없는","sense":"lasting a short time"},
                  {"lang":"Korean","lang_code":"ko","word":"순간적인","sense":"lasting a short time"},
                  {"lang":"French","lang_code":"fr","word":"éphémère"}]},
 {"word":"ephemeral","lang":"English","lang_code":"en","pos":"noun",
  "senses":[{"glosses":["Something which lasts for a short period of time."]}]},
 {"word":"apples","lang":"English","lang_code":"en","pos":"noun",
  "senses":[{"glosses":["plural of apple"],"form_of":[{"word":"apple"}],"tags":["form-of","plural"]}]},
 {"word":"apple","lang":"English","lang_code":"en","pos":"noun","sounds":[{"ipa":"/ˈæp.əl/"}],
  "etymology_text":"From Middle English appel, from Old English æppel.",
  "senses":[{"glosses":["A common, round fruit produced by the tree Malus domestica."],
             "examples":[{"text":"She ate an apple.","type":"example"}],
             "translations":[{"lang":"Korean","lang_code":"ko","word":"사과","sense":"fruit"}]}]},
 {"word":"London","lang":"English","lang_code":"en","pos":"name","senses":[{"glosses":["capital of UK"]}]},
 {"word":"Seoul","lang":"English","lang_code":"en","pos":"name","senses":[{"glosses":["capital of South Korea"]}],
  "translations":[{"lang":"Korean","lang_code":"ko","word":"서울"}]},
 {"word":"pomme","lang":"French","lang_code":"fr","pos":"noun","senses":[{"glosses":["apple"]}]},
 {"word":"사과","lang":"Korean","lang_code":"ko","pos":"noun",
  "forms":[{"form":"沙果","tags":["hanja"]},{"form":"sagwa","tags":["romanization"]}],
  "sounds":[{"ipa":"[sʰa̠ɡwa̠]"}],
  "senses":[{"glosses":["apple"],"examples":[{"text":"사과를 먹다","english":"to eat an apple"}]}]},
 {"word":"run","lang":"English","lang_code":"en","pos":"verb","senses":[{"glosses":["To move swiftly."]}]},
 {"word":"running","lang":"English","lang_code":"en","pos":"verb","senses":[{"glosses":["present participle of run"],"form_of":[{"word":"run"}]}]},
]
ko = [
 {"word":"ephemeral","lang":"영어","lang_code":"en","pos":"adj","pos_title":"형용사",
  "senses":[{"glosses":["수명이 짧은, 덧없는"]},{"glosses":["하루살이의"],"examples":[{"text":"ephemeral insects","translation":"하루살이 곤충"}]}],
  "sounds":[{"ipa":"ɪˈfem.ər.əl"}]},
 {"word":"사과","lang":"한국어","lang_code":"ko","pos":"noun","pos_title":"명사",
  "senses":[{"glosses":["사과나무의 열매."]},{"glosses":["자기의 잘못을 인정하고 용서를 빎."]}]},
 {"word":"Apfel","lang":"독일어","lang_code":"de","pos":"noun","senses":[{"glosses":["사과"]}]},
]
def w(name, rows, compact):
    with gzip.open(os.path.join(out,name),"wt",encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",",":") if compact else (", ",": "))+"\n")
w("en.jsonl.gz", en, False); w("ko.jsonl.gz", ko, True)

# 국립국어원 '사전 내려받기' 형식 샘플 (표준국어대사전 zip + 우리말샘 json)
import zipfile
def std(code, word, sup, hanja, pron, pos_list, rel=None):
    return {"target_code": code, "word_info": {
        "word": word, "sup_no": sup, "word_unit": "단어", "word_type": "한자어",
        "original_language_info": [{"original_language": hanja, "language_type": "한자"}] if hanja else [],
        "pronunciation_info": [{"pronunciation": pron}] if pron else [],
        "pos_info": [{"pos_code": i, "pos": pos, "comm_pattern_info": [{"comm_pattern_code": 1, "sense_info": [
            {"sense_code": j, "type": "일반어", "definition": d, "definition_original": d,
             "example_info": [{"example": ex, "source": ""} for ex in exs]
                             + [{"example": "인용 예문이라 빠져야 함", "source": "≪어느 소설≫"}],
             "lexical_info": rel or []} for j, (d, exs) in enumerate(senses, 1)]}]}
            for i, (pos, senses) in enumerate(pos_list, 1)]}}
std_items = [
    std(1, "사과", 1, "沙果", "사과", [("명사", [("사과나무의 열매. <FL>둥글고</FL> 붉으며 맛이 새콤달콤하다.", ["{사과}를 깎다."])])]),
    std(2, "사과", 2, "謝過", "사ː과", [("명사", [("자기의 잘못을 인정하고 용서를 빎.", ["{사과}의 말씀을 드리다."])])],
        rel=[{"word": "사죄01", "type": "비슷한말"}]),
    std(3, "아름-답다", 0, "", "아름답따", [("형용사", [("보이는 대상이나 음향, 목소리 따위가 균형과 조화를 이루어 눈과 귀에 즐거움과 만족을 줄 만하다.", ["경치가 {아름답다}."])])]),
    std(4, "가게^기둥에^입춘", 0, "", "", [("", [("격에 어울리지 않음을 비유적으로 이르는 말.", [])])]),
    std(5, "됐다", 0, "", "", [("", [("‘되었다’의 준말.", [])])]),
]
with zipfile.ZipFile(os.path.join(out, "stdict.zip"), "w") as z:
    z.writestr("1_5000_20261028.json", json.dumps({"channel": {"total": len(std_items), "item": std_items}}, ensure_ascii=False))
open_items = [
    {"target_code": 9001, "wordinfo": {"word": "사과", "sup_no": 1, "word_unit": "단어"},
     "senseinfo": {"pos": "명사", "type": "일반어", "definition": "사과나무의 열매. 둥글고 붉으며 맛이 새콤달콤하다."}},
    {"target_code": 9002, "wordinfo": {"word": "누리-소통망", "word_unit": "단어"},
     "senseinfo": {"pos": "명사", "type": "일반어", "definition": "온라인에서 사용자가 인맥을 쌓을 수 있게 해 주는 서비스.",
                   "cat_info": [{"cat": "정보·통신"}], "relation_info": [{"word": "에스엔에스", "type": "비슷한말"}]}},
    {"target_code": 9002, "wordinfo": {"word": "누리-소통망", "word_unit": "단어"},
     "senseinfo": {"pos": "명사", "type": "일반어", "definition": "두 번째 뜻."}},
]
with open(os.path.join(out, "opendict.json"), "w", encoding="utf-8") as f:
    json.dump({"channel": {"total": 3, "item": open_items}}, f, ensure_ascii=False)
