#include "fission/io/Sab.h"

#include <cstring>

namespace fission::io::sab {
namespace {

constexpr char kMagic[] = "ASM BinaryFile4";
constexpr std::size_t kMagicLen = sizeof(kMagic) - 1;

class Lexer {
public:
    explicit Lexer(std::span<const std::uint8_t> data) : m_data(data) {}

    [[nodiscard]] bool atEnd() const { return m_pos >= m_data.size(); }
    [[nodiscard]] std::size_t pos() const { return m_pos; }
    void seek(std::size_t pos) { m_pos = pos; }

    template <typename T> T raw() {
        need(sizeof(T));
        T value;
        std::memcpy(&value, m_data.data() + m_pos, sizeof(T)); // file is little-endian, as is x86/ARM Linux
        m_pos += sizeof(T);
        return value;
    }

    // Returns false for the record terminator.
    bool next(Token& tok) {
        const std::size_t start = m_pos;
        const std::uint8_t tag = raw<std::uint8_t>();
        tok.s.clear();
        switch (tag) {
        case 0x02: tok.kind = TokenKind::Char; tok.i = raw<std::int8_t>(); break;
        case 0x03: tok.kind = TokenKind::Short; tok.i = raw<std::int16_t>(); break;
        case 0x04: tok.kind = TokenKind::Long; tok.i = raw<std::int32_t>(); break;
        case 0x05: tok.kind = TokenKind::Float; tok.d[0] = raw<float>(); break;
        case 0x06: tok.kind = TokenKind::Double; tok.d[0] = raw<double>(); break;
        case 0x07: tok.kind = TokenKind::String; str(tok, raw<std::uint8_t>()); break;
        case 0x08: tok.kind = TokenKind::String; str(tok, raw<std::uint16_t>()); break;
        case 0x09:
        case 0x12: tok.kind = TokenKind::String; str(tok, raw<std::uint32_t>()); break;
        case 0x0A: tok.kind = TokenKind::True; break;
        case 0x0B: tok.kind = TokenKind::False; break;
        case 0x0C: tok.kind = TokenKind::Ref; tok.i = raw<std::int32_t>(); break;
        case 0x0D: tok.kind = TokenKind::Ident; str(tok, raw<std::uint8_t>()); break;
        case 0x0E: tok.kind = TokenKind::SubIdent; str(tok, raw<std::uint8_t>()); break;
        case 0x0F: tok.kind = TokenKind::SubtypeOpen; break;
        case 0x10: tok.kind = TokenKind::SubtypeClose; break;
        case 0x11: return false;
        case 0x13:
        case 0x14:
            tok.kind = tag == 0x13 ? TokenKind::Position : TokenKind::Vector;
            for (double& v : tok.d) {
                v = raw<double>();
            }
            break;
        case 0x15: tok.kind = TokenKind::Enum; tok.i = raw<std::int32_t>(); break;
        case 0x16:
            tok.kind = TokenKind::Vector2;
            tok.d[0] = raw<double>();
            tok.d[1] = raw<double>();
            tok.d[2] = 0.0;
            break;
        default:
            throw SabError("sab: unknown token tag " + std::to_string(tag) + " at offset " +
                           std::to_string(start));
        }
        return true;
    }

private:
    void need(std::size_t n) const {
        if (m_pos + n > m_data.size()) {
            throw SabError("sab: unexpected end of data");
        }
    }
    void str(Token& tok, std::size_t len) {
        need(len);
        tok.s.assign(reinterpret_cast<const char*>(m_data.data() + m_pos), len);
        m_pos += len;
    }

    std::span<const std::uint8_t> m_data;
    std::size_t m_pos = 0;
};

bool startsWith(const std::string& s, const char* prefix) {
    return s.rfind(prefix, 0) == 0;
}

} // namespace

double Token::number() const {
    switch (kind) {
    case TokenKind::Double:
    case TokenKind::Float:
        return d[0];
    case TokenKind::Long:
    case TokenKind::Short:
    case TokenKind::Char:
    case TokenKind::Enum:
        return static_cast<double>(i);
    default:
        throw SabError("sab: token is not a number");
    }
}

bool hasMagic(std::span<const std::uint8_t> data) {
    return data.size() >= kMagicLen && std::memcmp(data.data(), kMagic, kMagicLen) == 0;
}

Document parse(std::span<const std::uint8_t> data) {
    if (!hasMagic(data)) {
        throw SabError("sab: not an ASM BinaryFile4 blob");
    }
    Document doc;
    Lexer lex(data);
    lex.seek(kMagicLen);
    doc.version = lex.raw<std::int64_t>();
    (void)lex.raw<std::int32_t>();
    (void)lex.raw<std::int32_t>();

    // Header: product, ASM version, date (strings), then units, resabs, resnor (doubles),
    // then the first record identifier.
    std::vector<Token> preamble;
    Token tok;
    while (true) {
        const std::size_t before = lex.pos();
        if (!lex.next(tok)) {
            throw SabError("sab: terminator in header");
        }
        if (tok.kind == TokenKind::Ident || tok.kind == TokenKind::SubIdent) {
            lex.seek(before);
            break;
        }
        preamble.push_back(tok);
    }
    std::vector<std::string> strings;
    std::vector<double> numbers;
    for (const Token& t : preamble) {
        if (t.kind == TokenKind::String) {
            strings.push_back(t.s);
        } else if (t.kind == TokenKind::Double) {
            numbers.push_back(t.d[0]);
        }
    }
    if (strings.size() >= 3) {
        doc.product = strings[0];
        doc.asmVersion = strings[1];
        doc.date = strings[2];
    }
    if (numbers.size() >= 3) {
        doc.mmPerUnit = numbers[0];
        doc.resabs = numbers[1];
        doc.resnor = numbers[2];
    }

    while (!lex.atEnd()) {
        Record rec;
        bool inName = true;
        while (lex.next(tok)) {
            if (inName && (tok.kind == TokenKind::SubIdent || tok.kind == TokenKind::Ident)) {
                if (!rec.type.empty()) {
                    rec.type += '-';
                }
                rec.type += tok.s;
                if (tok.kind == TokenKind::Ident) {
                    inName = false;
                }
                continue;
            }
            inName = false;
            rec.values.push_back(std::move(tok));
            tok = Token{};
        }
        if (startsWith(rec.type, "Begin-of-ASM-History") || startsWith(rec.type, "End-of-ASM")) {
            break;
        }
        doc.records.push_back(std::move(rec));
    }
    return doc;
}

} // namespace fission::io::sab
