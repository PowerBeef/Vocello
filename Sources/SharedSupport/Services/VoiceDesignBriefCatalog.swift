import Foundation
import QwenVoiceCore

/// Single source of truth for the Voice Design brief product copy + limits,
/// shared by the iOS brief sheet (`IOSVoiceDesignBriefSheet`) and the macOS
/// inline editor (`MacVoiceBriefEditor`).
enum VoiceDesignBriefCatalog {
    /// Voice Design BRIEF (the voice DESCRIPTION) limit — deliberately
    /// decoupled from the spoken-script limit. Research on the official
    /// Qwen3-TTS VoiceDesign docs found no model-imposed description cap for
    /// the open-weights model; the hosted API caps voice_prompt at 2048 chars,
    /// and official example descriptions are short (one dense sentence,
    /// ~21–160 chars). 500 fits 2–3 dense sentences with headroom while
    /// discouraging paragraph-length rambling the examples suggest is
    /// unnecessary.
    static let descriptionLimit = 500

    /// Research-aligned (official Qwen3-TTS VoiceDesign guidance): each brief
    /// combines several dimensions from the official voice-design table —
    /// gender, age, pitch, pace, emotion, timbre, and purpose/use-case — in one
    /// dense sentence, the shape the model's own example descriptions use.
    /// The last four mirror official example archetypes (documentary narrator,
    /// fast upbeat commercial voice, animation child voice, and the
    /// persona-plus-delivery-mechanics teenager from the design-then-clone
    /// example). Accent wording is a flavor hint, not a guarantee — instruct
    ///-driven accent/dialect control is unreliable on the open checkpoints.
    ///
    /// Always name a **gender** and, when pitch matters, a **concrete register**
    /// ("low, bass-resonant" — not just "deep"). Voice Design samples a fresh
    /// voice per call (no fixed speaker, talker temp 0.9), so an under-specified
    /// brief lets it sample a higher or different-gender voice — a gender-less
    /// "deep narrator" can come out high-pitched. Concrete, gendered defaults
    /// keep that tail tight.
    static let startingPoints = [
        "A deep, low-pitched male narrator, warm and bass-resonant, with a subtle British accent.",
        "A bright young woman, energetic and conversational.",
        "A gravelly, low-pitched older man, slow and intimate, late-night radio.",
        "A soft, breathy young woman, gentle and reassuring.",
        "A calm middle-aged male voice with slow pace and a deep, magnetic tone, ideal for documentary narration.",
        "A lively young female voice with fast pace and upward intonation, suited to upbeat product videos.",
        "A cute child's voice, around eight years old, slightly mischievous, suited to animated characters.",
        "A teenage male voice, tenor range, gaining confidence, though the vowels still tighten when he is nervous.",
    ]

    static func startingPoints(in language: Qwen3SupportedLanguage) -> [String] {
        StudioPromptContent.copy(for: language).starters
    }

    static func placeholder(in language: Qwen3SupportedLanguage) -> String {
        language == .english || language == .auto ? placeholder : startingPoints(in: language)[0]
    }

    static let placeholder = "A warm, deep male narrator with a low, resonant tone and a subtle British accent."
}

/// Speech-language content, deliberately independent of the interface's compiled locales.
/// Starters become editable model input only after an explicit selection. Delivery copy is
/// presentation only: canonical preset IDs and instructions never come from these translations.
enum StudioPromptContent {
    struct DeliveryCopy: Sendable {
        let name: String
        let detail: String
    }

    struct Copy: Sendable {
        let starters: [String]
        let deliveries: [String: DeliveryCopy]
    }

    static func language(
        selected: Qwen3SupportedLanguage,
        detected: Qwen3SupportedLanguage,
        interfaceLanguage: String
    ) -> Qwen3SupportedLanguage {
        let effective = LanguageSelectionPresentation.effective(selected: selected, detected: detected)
        guard effective == .auto else { return effective }
        switch Locale(identifier: interfaceLanguage).language.languageCode?.identifier {
        case "fr": return .french
        case "de": return .german
        case "es": return .spanish
        case "it": return .italian
        case "pt": return .portuguese
        case "zh": return .chinese
        case "ja": return .japanese
        case "ko": return .korean
        case "ru": return .russian
        default: return .english
        }
    }

    static func deliveryName(_ presetID: String, in language: Qwen3SupportedLanguage) -> String {
        copy(for: language).deliveries[presetID]?.name ?? presetID.capitalized
    }

    static func directionalHintAdvisory(in language: Qwen3SupportedLanguage) -> String {
        switch language {
        case .french:
            "Ces indications modulent l'énergie et le rythme, mais l'émotion choisie n'est pas toujours perceptible. Régénérez pour explorer, ou clonez une voix de référence exprimant cette émotion pour une interprétation plus fiable."
        case .spanish:
            "Estas indicaciones moldean la energía y el ritmo, pero la emoción elegida no siempre se percibe. Vuelve a generar para explorar o clona una voz de referencia con esa emoción para una interpretación más fiable."
        case .german:
            "Diese Hinweise beeinflussen Energie und Tempo, doch die gewählte Emotion ist nicht immer hörbar. Erzeuge weitere Varianten oder klone eine Referenzstimme mit dieser Emotion für eine verlässlichere Darbietung."
        case .italian:
            "Queste indicazioni modulano energia e ritmo, ma l'emozione scelta non è sempre percepibile. Rigenera per esplorare oppure clona una voce di riferimento con quell'emozione per un'interpretazione più affidabile."
        case .portuguese:
            "Estas indicações moldam a energia e o ritmo, mas a emoção escolhida nem sempre fica perceptível. Gere novamente para explorar ou clone uma voz de referência com essa emoção para uma interpretação mais consistente."
        case .chinese:
            "这些提示能调整活力和节奏，但每次生成未必都能传达所选情绪。可以重新生成以探索不同效果，或克隆带有该情绪的参考声音，以获得更稳定的表达。"
        case .japanese:
            "これらのヒントは勢いやテンポを変えますが、選んだ感情が毎回伝わるとは限りません。再生成して試すか、その感情を含む参照音声をクローンすると、より安定した表現が得られます。"
        case .korean:
            "이 힌트는 활력과 속도를 조절하지만 선택한 감정이 매번 드러나지는 않을 수 있습니다. 다시 생성하여 비교하거나 해당 감정이 담긴 참조 음성을 복제하면 더 일관된 표현을 얻을 수 있습니다."
        case .russian:
            "Эти подсказки меняют энергичность и темп, но выбранная эмоция может проявляться не в каждом дубле. Попробуйте повторную генерацию или клонируйте эталонный голос с нужной эмоцией для более стабильной подачи."
        case .english, .auto:
            EmotionPreset.directionalHintAdvisory
        }
    }

    static func delivery(_ preset: EmotionPreset, in language: Qwen3SupportedLanguage) -> DeliveryCopy {
        copy(for: language).deliveries[preset.id] ?? DeliveryCopy(name: preset.label, detail: "")
    }

    static func copy(for language: Qwen3SupportedLanguage) -> Copy {
        translations[language] ?? english
    }

    private static func deliveryCopy(_ pairs: [(String, String)]) -> [String: DeliveryCopy] {
        let ids = ["neutral", "happy", "sad", "angry", "fearful", "surprised", "whisper", "calm"]
        return Dictionary(uniqueKeysWithValues: zip(ids, pairs).map {
            ($0.0, DeliveryCopy(name: $0.1.0, detail: $0.1.1))
        })
    }

    private static let english = Copy(starters: VoiceDesignBriefCatalog.startingPoints, deliveries: deliveryCopy([
        ("Neutral", "Default, even pacing"), ("Happy", "Bright lift; can read as surprise"),
        ("Sad", "Quiet, slower, somber"), ("Angry", "Hard, driving push"),
        ("Fearful", "Soft, unsteady; can read as sad"), ("Surprised", "Pitch jumps, quick catches"),
        ("Whisper", "Soft, close-mic breath"), ("Calm", "Slower, reassuring"),
    ]))

    // Translated starter content preserves each brief's intent, including any requested accent.
    // Selecting French does not silently replace a British-accent request with a Quebec accent.
    // These examples are editable suggestions, not a claim of measured multilingual adherence.
    private static let translations: [Qwen3SupportedLanguage: Copy] = [
        .french: Copy(starters: [
            "Un narrateur à la voix masculine grave, chaleureuse et résonnante dans les basses, avec un léger accent britannique.",
            "Une jeune femme à la voix claire, énergique et naturelle, comme dans une conversation.",
            "Un homme âgé à la voix grave et rocailleuse, au débit lent et intime, comme à la radio tard le soir.",
            "Une jeune femme à la voix douce et légèrement soufflée, délicate et rassurante.",
            "Une voix masculine calme, d'âge mûr, au débit lent et au timbre grave et captivant, idéale pour un documentaire.",
            "Une jeune voix féminine vive, au débit rapide et à l'intonation montante, pour des vidéos de présentation dynamiques.",
            "Une charmante voix d'enfant d'environ huit ans, légèrement espiègle, pour des personnages de dessin animé.",
            "Une voix masculine adolescente, dans le registre de ténor, qui gagne en assurance mais dont les voyelles restent tendues sous l'effet du stress.",
        ], deliveries: deliveryCopy([
            ("Neutre", "Naturel, rythme régulier"), ("Joyeux", "Élan lumineux, parfois proche de la surprise"),
            ("Triste", "Doux, plus lent, sombre"), ("En colère", "Ferme, intense, énergique"),
            ("Craintif", "Doux, hésitant, parfois proche de la tristesse"), ("Surpris", "Sauts de hauteur, brèves reprises"),
            ("Chuchoté", "Souffle doux, proche du micro"), ("Calme", "Plus lent, rassurant"),
        ])),
        .spanish: Copy(starters: [
            "Un narrador de voz masculina grave, cálida y resonante en los bajos, con un ligero acento británico.",
            "Una mujer joven de voz clara, enérgica y conversacional.",
            "Un hombre mayor de voz grave y rasposa, lenta e íntima, como en la radio de madrugada.",
            "Una mujer joven de voz suave y ligeramente aireada, delicada y tranquilizadora.",
            "Una voz masculina de mediana edad, serena, de ritmo lento y tono grave y cautivador, ideal para documentales.",
            "Una voz femenina joven y animada, de ritmo rápido y entonación ascendente, para vídeos de productos dinámicos.",
            "Una tierna voz infantil de unos ocho años, un poco traviesa, para personajes animados.",
            "Una voz masculina adolescente, de registro tenor, que gana confianza aunque las vocales aún se tensan cuando está nervioso.",
        ], deliveries: deliveryCopy([
            ("Neutro", "Natural, ritmo uniforme"), ("Alegre", "Brillante; puede sonar sorprendido"),
            ("Triste", "Suave, más lento, sombrío"), ("Enfadado", "Firme, intenso, enérgico"),
            ("Temeroso", "Suave, inseguro; puede sonar triste"), ("Sorprendido", "Saltos de tono, breves pausas"),
            ("Susurro", "Aliento suave, cerca del micrófono"), ("Calmado", "Más lento, tranquilizador"),
        ])),
        .german: Copy(starters: [
            "Ein männlicher Erzähler mit tiefer, warmer, bassreicher Stimme und leicht britischem Akzent.",
            "Eine junge Frau mit heller, energischer und gesprächiger Stimme.",
            "Ein älterer Mann mit rauer, tiefer Stimme, langsam und vertraulich wie im nächtlichen Radio.",
            "Eine junge Frau mit weicher, leicht hauchiger Stimme, sanft und beruhigend.",
            "Eine ruhige männliche Stimme mittleren Alters, mit langsamem Tempo und tiefem, fesselndem Klang, ideal für Dokumentationen.",
            "Eine lebhafte junge Frauenstimme mit schnellem Tempo und steigender Intonation für schwungvolle Produktvideos.",
            "Eine niedliche Kinderstimme, etwa acht Jahre alt und etwas schelmisch, für Zeichentrickfiguren.",
            "Eine männliche Teenagerstimme in Tenorlage, zunehmend selbstsicher, deren Vokale bei Nervosität noch angespannt klingen.",
        ], deliveries: deliveryCopy([
            ("Neutral", "Natürlich, gleichmäßiges Tempo"), ("Fröhlich", "Hell und beschwingt; teils überrascht"),
            ("Traurig", "Leise, langsamer, bedrückt"), ("Wütend", "Hart, drängend, energisch"),
            ("Ängstlich", "Leise, unsicher; teils traurig"), ("Überrascht", "Tonsprünge, kurze Unterbrechungen"),
            ("Flüstern", "Leiser Atem, nah am Mikrofon"), ("Ruhig", "Langsamer, beruhigend"),
        ])),
        .italian: Copy(starters: [
            "Un narratore dalla voce maschile grave, calda e risonante nei bassi, con un lieve accento britannico.",
            "Una giovane donna dalla voce luminosa, energica e colloquiale.",
            "Un uomo anziano dalla voce roca e grave, lenta e intima, come alla radio di notte.",
            "Una giovane donna dalla voce morbida e leggermente soffiata, delicata e rassicurante.",
            "Una voce maschile di mezza età, calma, dal ritmo lento e dal timbro grave e magnetico, ideale per documentari.",
            "Una giovane voce femminile vivace, dal ritmo rapido e dall'intonazione ascendente, per video di prodotti dinamici.",
            "Una graziosa voce infantile di circa otto anni, un po' birichina, per personaggi animati.",
            "Una voce maschile adolescente nel registro di tenore, sempre più sicura, con vocali ancora tese quando è nervoso.",
        ], deliveries: deliveryCopy([
            ("Neutro", "Naturale, ritmo regolare"), ("Felice", "Slancio luminoso; a volte sorpreso"),
            ("Triste", "Sommesso, più lento, cupo"), ("Arrabbiato", "Deciso, intenso, incalzante"),
            ("Impaurito", "Sommesso, incerto; a volte triste"), ("Sorpreso", "Salti di tono, brevi interruzioni"),
            ("Sussurro", "Soffio lieve, vicino al microfono"), ("Calmo", "Più lento, rassicurante"),
        ])),
        .portuguese: Copy(starters: [
            "Um narrador de voz masculina grave, calorosa e ressonante nos baixos, com um leve sotaque britânico.",
            "Uma jovem mulher de voz clara, enérgica e natural, como em uma conversa.",
            "Um homem mais velho de voz grave e rouca, lenta e íntima, como no rádio de madrugada.",
            "Uma jovem mulher de voz suave e levemente soprosa, delicada e tranquilizadora.",
            "Uma voz masculina de meia-idade, calma, de ritmo lento e timbre grave e envolvente, ideal para documentários.",
            "Uma jovem voz feminina animada, de ritmo rápido e entonação ascendente, para vídeos dinâmicos de produtos.",
            "Uma voz infantil encantadora, de cerca de oito anos, um pouco travessa, para personagens de animação.",
            "Uma voz masculina adolescente, no registro de tenor, ganhando confiança, embora as vogais ainda fiquem tensas quando está nervoso.",
        ], deliveries: deliveryCopy([
            ("Neutro", "Natural, ritmo uniforme"), ("Alegre", "Brilhante; pode soar surpreso"),
            ("Triste", "Suave, mais lento, sombrio"), ("Irritado", "Firme, intenso, enérgico"),
            ("Temeroso", "Suave, instável; pode soar triste"), ("Surpreso", "Saltos de tom, breves pausas"),
            ("Sussurro", "Sopro suave, perto do microfone"), ("Calmo", "Mais lento, tranquilizador"),
        ])),
        .chinese: Copy(starters: [
            "一位男旁白，音调低沉，声音温暖、低音浑厚，带轻微的英式口音。",
            "一位年轻女性，声音明亮、充满活力，语气自然，如同日常交谈。",
            "一位年长男性，声音低沉沙哑，语速缓慢、亲切，像深夜电台主持人。",
            "一位年轻女性，声音柔和，略带气声，温柔而令人安心。",
            "平静的中年男性声音，语速缓慢，音色低沉而富有磁性，适合纪录片旁白。",
            "活泼的年轻女性声音，语速较快，语调上扬，适合轻快的产品视频。",
            "大约八岁的可爱童声，略带调皮，适合动画角色。",
            "青春期男性声音，男高音音域，逐渐变得自信，但紧张时元音仍显得紧绷。",
        ], deliveries: deliveryCopy([
            ("中性", "自然，节奏均匀"), ("开心", "明亮轻快，有时像惊讶"),
            ("悲伤", "轻柔、较慢、低落"), ("愤怒", "强硬、有力、急切"),
            ("害怕", "轻柔、不稳定，有时像悲伤"), ("惊讶", "音调跳跃，短促停顿"),
            ("耳语", "轻柔气声，贴近麦克风"), ("平静", "较慢，令人安心"),
        ])),
        .japanese: Copy(starters: [
            "低い声の男性ナレーター。温かく豊かな低音で、かすかにイギリス訛りがある。",
            "明るい声の若い女性。元気で、自然な会話調。",
            "低くしわがれた声の年配男性。深夜ラジオのように、ゆっくりと親密に話す。",
            "柔らかく少し息混じりの声の若い女性。優しく、安心感がある。",
            "落ち着いた中年男性の声。ゆっくりとしたペースと深く魅力的な響きで、ドキュメンタリーの語りに適している。",
            "生き生きとした若い女性の声。速いペースと上がり調子のイントネーションで、明るい商品紹介動画に適している。",
            "八歳くらいのかわいらしい子どもの声。少しいたずらっぽく、アニメのキャラクターに適している。",
            "十代の男性の声。テノールの音域で自信がつき始めているが、緊張すると母音がまだこわばる。",
        ], deliveries: deliveryCopy([
            ("ニュートラル", "自然で一定のペース"), ("喜び", "明るい弾み。驚きに聞こえることも"),
            ("悲しみ", "静かで遅く、沈んだ調子"), ("怒り", "強く、勢いのある調子"),
            ("恐れ", "弱く不安定。悲しみに聞こえることも"), ("驚き", "音程の跳躍と短い間"),
            ("ささやき", "マイクに近い柔らかな息声"), ("穏やか", "ゆっくりと安心させる調子"),
        ])),
        .korean: Copy(starters: [
            "낮은 음역의 남성 내레이터. 따뜻하고 저음이 풍부하며 약한 영국식 억양이 있다.",
            "밝은 목소리의 젊은 여성. 활기차고 자연스럽게 대화하듯 말한다.",
            "낮고 거친 목소리의 나이 든 남성. 심야 라디오처럼 느리고 친밀하게 말한다.",
            "부드럽고 약간 숨소리가 섞인 젊은 여성의 목소리. 다정하고 안심을 준다.",
            "차분한 중년 남성의 목소리. 느린 속도와 깊고 매력적인 음색으로 다큐멘터리 해설에 어울린다.",
            "생기 있는 젊은 여성의 목소리. 빠른 속도와 올라가는 억양으로 경쾌한 제품 영상에 어울린다.",
            "여덟 살 정도의 귀여운 아이 목소리. 조금 장난스러우며 애니메이션 캐릭터에 어울린다.",
            "테너 음역의 십 대 남성 목소리. 점차 자신감이 생기지만 긴장하면 모음 발음이 아직 굳어진다.",
        ], deliveries: deliveryCopy([
            ("중립", "자연스럽고 일정한 속도"), ("기쁨", "밝은 활력, 놀람처럼 들릴 수 있음"),
            ("슬픔", "조용하고 느리며 침울함"), ("분노", "강하고 몰아치는 힘"),
            ("두려움", "부드럽고 불안정함, 슬픔처럼 들릴 수 있음"), ("놀람", "음높이의 도약과 짧은 멈춤"),
            ("속삭임", "마이크 가까이서 부드러운 숨소리"), ("차분함", "느리고 안심을 주는 말투"),
        ])),
        .russian: Copy(starters: [
            "Мужчина-рассказчик с низким, тёплым, басовитым голосом и лёгким британским акцентом.",
            "Молодая женщина с ярким, энергичным голосом и естественной разговорной манерой.",
            "Пожилой мужчина с низким хрипловатым голосом, медленной и доверительной манерой, как на ночном радио.",
            "Молодая женщина с мягким голосом и лёгким придыханием, нежная и успокаивающая.",
            "Спокойный мужской голос среднего возраста, медленный темп и глубокий притягательный тембр, подходящий для документального фильма.",
            "Живой голос молодой женщины, быстрый темп и восходящие интонации для энергичных роликов о продуктах.",
            "Милый голос ребёнка примерно восьми лет, слегка озорной, для персонажей мультфильмов.",
            "Мужской подростковый голос в теноровом диапазоне, набирающий уверенность, но гласные ещё звучат напряжённо при волнении.",
        ], deliveries: deliveryCopy([
            ("Нейтрально", "Естественно, ровный темп"), ("Радостно", "Яркий подъём; иногда как удивление"),
            ("Грустно", "Тихо, медленнее, мрачно"), ("Сердито", "Жёстко, напористо, энергично"),
            ("Испуганно", "Тихо, неуверенно; иногда как грусть"), ("Удивлённо", "Скачки тона, короткие паузы"),
            ("Шёпотом", "Тихое дыхание у микрофона"), ("Спокойно", "Медленнее, успокаивающе"),
        ])),
    ]
}
