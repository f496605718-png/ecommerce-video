# AIShotStudio Text to Video Prompt Structure（文生视频提示词结构）

> 来源：https://aishotstudio.com/text-to-video-prompt-structure/
> 说明：文生视频提示词的两种组织格式：连续文本版 + JSON 结构化版。核心模块：视觉细节 / 镜头（构图+运镜+角度）/ 光影 / 技术镜头参数 / 对白音频。

## 连续文本版结构（Continuous Block）

```
[Visuals] 视觉风格+主体+场景+动作细节
[Camera] Composition 构图, Motion 运镜, Angle 角度
[Lighting] 光影风格
[Technical Lens] 焦段+光圈+胶片颗粒
[Dialogue/Audio] 对白+"音频氛围说明（如 NO MUSIC）"
```

### 示例（电影 Noir 侦探）

> [Visuals] Neo-Noir, Cinematic 4k, 1950s Film Style. A grizzled detective sits behind a cluttered desk with a glass ashtray in a dim office. The room is filled with a thick, static atmospheric haze, but there are no visible cigarettes or smoke plumes. He leans forward, holding a photograph so the viewer sees ONLY the blank, white back of the photo paper. He lowers the photo, leans back in his creaking leather chair with a look of exhausted triumph, and speaks directly to the air. Medium Shot, Center Framed, Slow Dolly In, Slight Low Angle. Low Key, Chiaroscuro, Volumetric Lighting (God Rays), Hard Shadows. 50mm Anamorphic, f/2.8, Film Grain.

> [Dialogue/Audio] "I told you I'd find the loose thread." (Spoken in a dry, gritty, monotone voice with exhausted relief). Audio should be silence, office room tone, hum of ventilation, and creaking chair only. NO MUSIC.

## JSON 结构化版（示例）

```json
{
  "global_parameters": {
    "style_reference": "Neo-Noir, 1950s Crime Drama, Photorealistic",
    "audio_ambiance": "Silence, office room tone, hum of ventilation, creaking chair, sound effects only, NO MUSIC"
  },
  "global_negative_prompt": ["singing", "musical", "background music", "musical score", "soundtrack", "melody", "rap", "floating cigarettes", "visible photo image", "smoke emitters", "burning objects"],
  "scene": [
    {
      "cinematic_prompt": {
        "visual_details": "A grizzled detective sits behind a cluttered desk with a glass ashtray in a dim office...",
        "camera": {
          "composition": "Medium Shot, Center Framed",
          "motion": "Slow Dolly In",
          "angle": "Slight Low Angle"
        },
        "lighting": "Low Key, Chiaroscuro, Volumetric Lighting (God Rays), Hard Shadows",
        "technical_lens": "50mm Anamorphic, f/2.8, Film Grain"
      },
      "dialogue": {
        "speaker": "Detective",
        "text": "I told you I'd find the loose thread.",
        "emotion": "Exhausted relief, serious, flat",
        "voice_style": "Dry spoken word, gritty speech, gravelly narration, monotone, conversational",
        "timing_trigger": "After leaning back"
      }
    }
  ]
}
```

## 七模块拆解（对客可解释）

| 模块 | 内容 | 对应项目七要素 |
|---|---|---|
| Style Reference | 风格参考（Neo-Noir/年代/写实度） | ③场景+调性 |
| Visual Details | 视觉细节（主体/动作/场景） | ①商品+②模特+③场景 |
| Camera Composition | 构图（景别/居中） | ⑤镜头 |
| Camera Motion | 运镜 | ⑥运镜 |
| Camera Angle | 角度 | ⑤镜头 |
| Lighting | 光影 | ④灯光 |
| Technical Lens | 焦段/光圈/颗粒 | ⑤镜头+画质收尾 |
| Dialogue/Audio | 对白+音频氛围 | （后期/音频层） |
