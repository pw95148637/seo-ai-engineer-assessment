"""Handwritten deterministic fixtures; no model call occurs."""
SAFE={"title":"娛樂城推薦怎麼看？先查出金條件、資安與風險的六個問題",
      "sections":["推薦前先說明：本文未完成平台實測，不提供獲利或提款保證",
                  "查核出金：身分驗證、費用、限額、處理時間與爭議管道",
                  "資安查核清單：個資處理與帳號保護；未查證項目標示未知",
                  "遊戲機率與資金損失：查明規則，不把短期結果當成長期勝率",
                  "平台比較表：條件、來源日期與缺漏；不製作未經驗證的排名",
                  "參與前確認所在地法律與年齡限制；設定預算及停止條件"]}
class Fixture:
    def __init__(self, scenario="conflict"):
        self.scenario=scenario; self.calls=0
    async def __call__(self,role,s):
        from workflow import TransientError
        self.calls+=1
        if self.scenario=="api_error": raise TransientError("injected 503")
        if self.scenario=="timeout":
            import asyncio
            await asyncio.sleep(1)
        if self.scenario=="malformed": return {"passed":"true"}
        if role=="planner":
            if self.scenario=="normal" or (s["iteration"]>1 and self.scenario!="stubborn"):
                return SAFE.copy()
            return {"title":"娛樂城推薦：穩賺不賠、保證出金","sections":["零風險獲利攻略"]}
        if self.scenario=="false_pass": return {"passed":True,"findings":[]}
        bad="保證出金" in s["draft"]["title"]
        return {"passed":not bad,"findings":[{"quote":"穩賺不賠、保證出金","reason":"無證據的獲利及提款保證會誤導讀者；與暫行規則衝突",
          "revision":"改以出金條件與資安查核問題吸引讀者，揭露損失風險，不宣稱已實測或審查通過","rule":"custom-provisional-v1/claims"}] if bad else []}
