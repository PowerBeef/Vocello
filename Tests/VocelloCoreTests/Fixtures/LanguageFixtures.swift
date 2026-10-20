import Foundation

/// Native script snippets for language-path unit tests. Train-themed sentences
/// long enough for NLLanguageRecognizer to exceed the 65% confidence floor.
enum LanguageFixtures {
    static let english = "The train left the station at dawn."
    static let french = "Le train a quitté la gare à l'aube."
    static let german = "Der Zug verließ den Bahnhof bei Tagesanbruch."
    static let spanish = "El tren salió de la estación al amanecer."
    static let italian = "Il treno è partito dalla stazione all'alba."
    static let portuguese = "O trem saiu da estação ao amanhecer."
    static let chinese = "火车在黎明时分离开了车站。"
    static let japanese = "列車は夜明けに駅を出発した。"
    static let korean = "기차는 새벽에 역을 떠났습니다."
    static let russian = "Поезд отправился со станции на рассвете."

    /// Below PromptLanguageDetector.minimumCharacters — must stay `.auto`.
    static let tooShort = "Hi"

    /// Long enough but not natural language — stays `.auto` at the confidence floor.
    static let ambiguousLatin = "x7k9 m2p4 q8w1 z3n6"

    /// Confidently Dutch, which Qwen3 does not speak, so detection yields `.auto`
    /// (the `macos auto-language` lane's undetected edge take).
    static let dutch = "De ochtendtrein verliet het rustige station op tijd."
}
