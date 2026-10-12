const express = require('express');
const { HowLongToBeatService } = require('howlongtobeat-ts');

const app = express();
const port = process.env.PORT || 3000;
const hltbService = new HowLongToBeatService();

/**
 * Normalizes title string by stripping special chars, trademarks, and bad encodings
 */
function cleanSpecialChars(str) {
    if (!str) return '';
    return str
        .replace(/[®™©]/g, '')
        .replace(/\uFFFD/g, '') // unicode replacement character
        .replace(/\s+/g, ' ')
        .trim();
}

/**
 * Searches HLTB for a single clean title using fallback strategies
 */
async function searchSingleTitle(rawTitle) {
    const title = cleanSpecialChars(rawTitle);
    if (!title) return null;

    // Generate candidate search queries in order of precision
    const queries = [];
    queries.push(title);

    // 1. If contains ' - ', replace with ': '
    if (title.includes(' - ')) {
        queries.push(title.replace(/ - /g, ': '));
    }

    // 2. If contains ' and ', replace with ' & '
    if (title.includes(' and ')) {
        queries.push(title.replace(/ and /g, ' & '));
    }
    if (title.includes(' & ')) {
        queries.push(title.replace(/ & /g, ' and '));
    }

    // 3. Remove text in parentheses: e.g. "Game (2023)", "Game (Remastered)"
    const noParens = title.replace(/\s*\([^)]*\)/g, '').trim();
    if (noParens && noParens !== title) {
        queries.push(noParens);
        if (noParens.includes(' - ')) {
            queries.push(noParens.replace(/ - /g, ': '));
        }
    }

    // 4. Strip common fluff keywords: Remake, Remastered, Complete Edition, etc.
    const stripped = title
        .replace(/\b(Remake|Remastered|Complete Edition|Anniversary Edition|Definitive Edition|Game of the YoRHa Edition|HD Remaster|VR)\b/gi, '')
        .replace(/\s+/g, ' ')
        .trim();
    if (stripped && stripped !== title) {
        queries.push(stripped);
        if (stripped.includes(' - ')) {
            queries.push(stripped.replace(/ - /g, ': '));
        }
    }

    // 5. If title has colon or dash, try just the prefix (main title)
    if (title.includes(':')) {
        const prefix = title.split(':')[0].trim();
        if (prefix.length > 3) queries.push(prefix);
    } else if (title.includes(' - ')) {
        const prefix = title.split(' - ')[0].trim();
        if (prefix.length > 3) queries.push(prefix);
    }

    // Deduplicate queries
    const uniqueQueries = [...new Set(queries)];

    for (const q of uniqueQueries) {
        try {
            const res = await hltbService.search(q);
            if (res && res.success && res.data && res.data.length > 0) {
                // Find best matching entry in results
                // Filter out non-games or zero-playtime if possible
                const validResults = res.data.filter(item => (item.mainExtraTime || item.mainTime));
                if (validResults.length > 0) {
                    return validResults[0];
                }
                return res.data[0];
            }
        } catch (err) {
            console.warn(`HLTB query failed for "${q}":`, err.message);
        }
    }

    return null;
}

/**
 * Searches for all DLCs of a game and sums up their playtime
 */
async function searchAllDlcs(baseTitle) {
    const cleanBase = cleanSpecialChars(baseTitle.replace(/\s*\(\s*All\s*DLC\s*\)/i, '').trim());
    try {
        const res = await hltbService.search(cleanBase);
        if (res && res.success && res.data && res.data.length > 0) {
            // Find all entries of type 'dlc'
            const dlcs = res.data.filter(item => item.type === 'dlc' && (item.mainExtraTime || item.mainTime));
            // Filter out minor 0.4h free DLCs/quests if there are major story expansions
            const majorDlcs = dlcs.filter(d => (d.mainExtraTime || d.mainTime) >= 3600); // >= 1 hour
            const dlcsToSum = majorDlcs.length > 0 ? majorDlcs : dlcs;

            if (dlcsToSum.length > 0) {
                let totalMain = 0;
                let totalMainExtra = 0;
                let totalComp = 0;
                for (const d of dlcsToSum) {
                    totalMain += (d.mainTime || 0) / 3600;
                    totalMainExtra += (d.mainExtraTime || d.mainTime || 0) / 3600;
                    totalComp += (d.completionistTime || d.mainExtraTime || 0) / 3600;
                }
                return {
                    name: `${cleanBase} (All DLC: ${dlcsToSum.map(d => d.name).join(' + ')})`,
                    main: totalMain,
                    mainExtra: totalMainExtra,
                    completionist: totalComp
                };
            }
        }
    } catch (err) {
        console.warn(`Error searching DLCs for "${baseTitle}":`, err.message);
    }
    return null;
}

/**
 * Main search router handling composite games (commas, DLCs, 'plus')
 */
async function resolvePlaytime(inputTitle) {
    const raw = inputTitle.trim();

    // Strategy 1: Check for "(All DLC)"
    if (/\(\s*All\s*DLC\s*\)/i.test(raw)) {
        const dlcResult = await searchAllDlcs(raw);
        if (dlcResult) return dlcResult;
        // Fallback to base game if DLC not found
        const base = raw.replace(/\(\s*All\s*DLC\s*\)/i, '').trim();
        const fallback = await searchSingleTitle(base);
        if (fallback) {
            return {
                name: fallback.name,
                main: fallback.mainTime ? fallback.mainTime / 3600 : null,
                mainExtra: fallback.mainExtraTime ? fallback.mainExtraTime / 3600 : null,
                completionist: fallback.completionistTime ? fallback.completionistTime / 3600 : null
            };
        }
    }

    // Strategy 2: Check for comma-separated collection: "Game 1, Game 2", "Teslagrad, Teslagrad 2"
    // Also "Tony Hawks Pro Skater 3 and 4"
    if (raw.includes(',') || /^(Tony Hawks? Pro Skater \d+) and (\d+)$/i.test(raw)) {
        let parts = [];
        const thpsMatch = raw.match(/^(Tony Hawks? Pro Skater) (\d+) and (\d+)$/i);
        if (thpsMatch) {
            parts = [`${thpsMatch[1]} ${thpsMatch[2]}`, `${thpsMatch[1]} ${thpsMatch[3]}`];
        } else {
            parts = raw.split(',').map(p => p.trim()).filter(Boolean);
        }

        // Check if this is "Poppy Playtime - Chapter 1, 2, 3, 4"
        const chapterSeriesMatch = raw.match(/^(.*?\bChapter)\s+(\d+)(?:\s*,\s*(\d+))+/i);
        if (chapterSeriesMatch) {
            const prefix = chapterSeriesMatch[1];
            const digits = raw.match(/\d+/g);
            if (digits) {
                parts = digits.map(d => `${prefix} ${d}`);
            }
        }

        if (parts.length > 1) {
            let sumMain = 0;
            let sumMainExtra = 0;
            let sumComp = 0;
            let foundCount = 0;
            const foundNames = [];

            for (const part of parts) {
                const item = await searchSingleTitle(part);
                if (item) {
                    foundCount++;
                    foundNames.push(item.name);
                    sumMain += (item.mainTime || 0) / 3600;
                    sumMainExtra += (item.mainExtraTime || item.mainTime || 0) / 3600;
                    sumComp += (item.completionistTime || item.mainExtraTime || 0) / 3600;
                }
            }

            if (foundCount > 0) {
                return {
                    name: `${raw} [Combined: ${foundNames.join(' + ')}]`,
                    main: sumMain,
                    mainExtra: sumMainExtra,
                    completionist: sumComp
                };
            }
        }
    }

    // Strategy 3: Check for "Game plus DLC" e.g. "Monster Hunter Rise plus Sunbreak", "Sea of Stars plus DLC Throes of the Watchmaker"
    if (/\bplus\b/i.test(raw)) {
        const plusParts = raw.split(/\bplus\b/i).map(s => s.trim());
        if (plusParts.length === 2) {
            const basePart = plusParts[0];
            const dlcPart = plusParts[1].replace(/^DLC\s+/i, '');
            const item1 = await searchSingleTitle(basePart);
            const item2 = await searchSingleTitle(`${basePart}: ${dlcPart}`) || await searchSingleTitle(dlcPart);

            if (item1 && item2) {
                return {
                    name: `${item1.name} + ${item2.name}`,
                    main: ((item1.mainTime || 0) + (item2.mainTime || 0)) / 3600,
                    mainExtra: ((item1.mainExtraTime || item1.mainTime || 0) + (item2.mainExtraTime || item2.mainTime || 0)) / 3600,
                    completionist: ((item1.completionistTime || item1.mainExtraTime || 0) + (item2.completionistTime || item2.mainExtraTime || 0)) / 3600
                };
            } else if (item1) {
                return {
                    name: item1.name,
                    main: item1.mainTime ? item1.mainTime / 3600 : null,
                    mainExtra: item1.mainExtraTime ? item1.mainExtraTime / 3600 : null,
                    completionist: item1.completionistTime ? item1.completionistTime / 3600 : null
                };
            }
        }
    }

    // Strategy 4: Standard single game search
    const single = await searchSingleTitle(raw);
    if (single) {
        return {
            name: single.name,
            main: single.mainTime ? single.mainTime / 3600 : null,
            mainExtra: single.mainExtraTime ? single.mainExtraTime / 3600 : null,
            completionist: single.completionistTime ? single.completionistTime / 3600 : null
        };
    }

    return null;
}

app.get('/search', async (req, res) => {
    const title = req.query.title;
    if (!title) {
        return res.status(400).json({ error: 'Title is required' });
    }

    try {
        const result = await resolvePlaytime(title);
        if (!result) {
            return res.status(404).json({ error: 'Not found' });
        }

        res.json({
            title: result.name,
            main: result.main,
            mainExtra: result.mainExtra,
            completionist: result.completionist
        });
    } catch (error) {
        console.error(`Error searching HLTB for "${title}":`, error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

app.listen(port, () => {
    console.log(`HLTB service listening on port ${port}`);
});
