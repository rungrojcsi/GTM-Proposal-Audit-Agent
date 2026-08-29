# Eval Harness

ทดสอบ pipeline ประเมิน proposal — แยก 2 โหมด

## Offline (รันได้เลย ไม่ต้องมี Azure)

```bash
cd eval
python run_eval.py
```

ตรวจ deterministic core (ไม่เรียก API):
- `_normalize_to_rubric` คืน **17 section เสมอ** (section ขาด → เติม missing=0, section แปลกปลอม → ตัดทิ้ง)
- tier ถูก **override ตาม rubric** (LLM เปลี่ยน tier ไม่ได้)
- score นอกช่วง → **clamp 0-10**
- คะแนนรวม **deterministic** (denominator คงที่ = 48, rubric v6: weight 4/3/1)
- verdict mapping ถูกที่ขอบเขต (v4: 7.0=Strong, 5.0=Adequate, 3.5=Weak, <3.5=Critical)

## Integration (เรียก GPT-4o จริง)

ตั้ง env ก่อน:
```bash
export AZURE_OPENAI_ENDPOINT="https://<...>.openai.azure.com/"
export AZURE_OPENAI_KEY="<key>"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"
export AZURE_OPENAI_API_VERSION="2024-08-01-preview"
pip install openai        # integration mode ต้องมี openai

python run_eval.py --integration
```

ตรวจกับ fixtures จริง:
- โครงสร้าง: 17 section + tier ตรง rubric (ทุก fixture)
- **relative ordering**: `strong_proposal` ต้องได้คะแนน > `weak_proposal`
- **anti-pattern**: `weak_proposal` ควรถูก flag (Why-Us-first, TBD team, one-number pricing) — soft check (เตือน ไม่ fail)

## Fixtures

| ไฟล์ | ออกแบบให้ |
|------|-----------|
| `fixtures/strong_proposal.txt` | ครบ 17 section, pain-first, named team, TCO breakdown, client-anchored schedule → ควรได้ Strong |
| `fixtures/weak_proposal.txt` | Why-Us-first, TBD team, ราคาเลขเดียว, ปิดด้วย Thank You, ไม่มี Cost of Inaction → ควรได้ Weak/Critical + โดน flag |

## เพิ่ม fixture ใหม่

วางไฟล์ `.txt` ใน `fixtures/` แล้วเพิ่มชื่อใน list ของ `run_integration()` (`run_eval.py`)
สำหรับ regression จริง แนะนำใส่ expected verdict range ต่อ fixture ในอนาคต

## Exit code

`0` = ผ่านทั้งหมด | `1` = มี check fail (ใช้ใน CI ได้)
