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
