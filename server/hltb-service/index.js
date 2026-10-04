const express = require('express');
const { HowLongToBeatService } = require('howlongtobeat-ts');

const app = express();
const port = process.env.PORT || 3000;
const hltbService = new HowLongToBeatService();

app.get('/search', async (req, res) => {
    const title = req.query.title;
    if (!title) {
        return res.status(400).json({ error: 'Title is required' });
    }

    try {
        const response = await hltbService.searchOne(title);
        if (!response || !response.success || !response.data) {
            return res.status(404).json({ error: 'Not found' });
        }

        const result = response.data;

        // The library returns time in seconds. We return it in hours.
        const main = result.mainTime ? result.mainTime / 3600 : null;
        const mainExtra = result.mainExtraTime ? result.mainExtraTime / 3600 : null;
        const completionist = result.completionistTime ? result.completionistTime / 3600 : null;

        res.json({
            title: result.name,
            main: main,
            mainExtra: mainExtra,
            completionist: completionist
        });
    } catch (error) {
        console.error(`Error searching HLTB for "${title}":`, error);
        res.status(500).json({ error: 'Internal server error' });
    }
});

app.listen(port, () => {
    console.log(`HLTB service listening on port ${port}`);
});
