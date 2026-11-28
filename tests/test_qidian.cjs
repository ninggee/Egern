'use strict';
const assert = require('node:assert/strict');
const {readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');
const code = readFileSync(path.join(__dirname, '../scripts/qidian.js'), 'utf8');
const origin = 'https://magev6.if.qidian.com/argus/api/';

function run(Data, endpoint = 'v1/client/getconf', method = 'POST') {
    const notifications = [], logs = [], outputs = [];
    vm.runInNewContext(code, {
        $request: {url: origin + endpoint, method},
        $response: {body: JSON.stringify({Data, Sentinel: 'keep top-level'})},
        $notification: {post: (...args) => notifications.push(args)},
        $done: value => outputs.push(value),
        console: {log: (...args) => logs.push(args)},
    }, {timeout: 1000});
    assert.equal(outputs.length, 1, 'exactly one completion');
    return {body: JSON.parse(outputs[0].body), notifications, logs};
}
function base() {
    return {
        WolfEye: 1,
        CloudSetting: {TeenShowFreq: '1', Keep: 42},
        ActivityIcon: {Type: 0, EndTime: 0, StartTime: 0},
        EnableSearchUser: '0',
        Sentinel: {keep: true},
    };
}
function assertOtherCleanup(result) {
    assert.equal(result.body.Data.WolfEye, 0);
    assert.equal(result.body.Data.CloudSetting.TeenShowFreq, '0');
    assert.equal(result.body.Data.CloudSetting.Keep, 42);
    assert.equal(result.body.Data.EnableSearchUser, '1');
    assert.deepEqual(result.body.Data.Sentinel, {keep: true});
    assert.equal(result.body.Sentinel, 'keep top-level');
}

for (const [label, value] of [
    ['missing', undefined], ['null', null], ['empty object', {}],
    ['null Data', {Data: null}], ['empty Data string', {Data: ''}],
    ['Data object', {Data: {Items: [1]}}], ['Data array', {Data: []}],
]) {
    test(`ActivityPopup: ${label}`, () => {
        const input = base();
        if (value !== undefined) input.ActivityPopup = value;
        const result = run(input);
        assert.equal(result.notifications.length, 0);
        assertOtherCleanup(result);
        if (value && value.Data) assert.equal(result.body.Data.ActivityPopup, null);
        else if (value === undefined) assert.equal('ActivityPopup' in result.body.Data, false);
        else assert.deepEqual(result.body.Data.ActivityPopup, value);
    });
}
for (const [label, value] of [
    ['missing', undefined], ['null', null], ['empty object', {}],
    ['array', []], ['string', 'unknown'], ['boolean', false],
    ['null Type', {Type: null, Keep: 42}],
    ['string Type', {Type: '0', EndTime: 123, Actionurl: 'keep'}],
    ['nonzero Type', {Type: 1, EndTime: 123, Actionurl: 'keep'}],
    ['object Type', {Type: {unknown: true}, Keep: 42}],
]) {
    test(`ActivityIcon: ${label} safely skipped, no guessed cleanup`, () => {
        const input = base();
        if (value === undefined) delete input.ActivityIcon;
        else input.ActivityIcon = value;
        const result = run(input);
        assert.equal(result.notifications.length, 0);
        assertOtherCleanup(result);
        if (value === undefined) assert.equal('ActivityIcon' in result.body.Data, false);
        else assert.deepEqual(result.body.Data.ActivityIcon, value);
        assert.ok(result.logs.some(args => String(args[0]).includes('跳过悬浮活动处理')));
        assert.ok(!result.logs.some(args => String(args[0]).startsWith('body:')));
    });
}
test('both optional configs absent: no notifications, other changes proceed', () => {
    const input = base(); delete input.ActivityIcon;
    const result = run(input);
    assert.equal(result.notifications.length, 0);
    assertOtherCleanup(result);
});
test('known Type=0 active icon is still cleared', () => {
    const input = base();
    input.ActivityIcon = {Type: 0, EndTime: 999, StartTime: 100, Actionurl: 'ad', Icon: 'ad.png', Keep: 42};
    const result = run(input);
    assert.deepEqual(result.body.Data.ActivityIcon, {Type: 0, EndTime: 0, StartTime: 0, Keep: 42});
    assert.equal(result.notifications.length, 0);
    assertOtherCleanup(result);
});
test('known Type=0 inactive icon remains unchanged', () => {
    const input = base();
    input.ActivityIcon.Keep = 'do not modify';
    const result = run(input);
    assert.deepEqual(result.body.Data.ActivityIcon, input.ActivityIcon);
    assert.equal(result.notifications.length, 0);
});
test('unrelated missing top-level Data diagnostic is retained', () => {
    const result = run(null);
    assert.ok(result.notifications.some(args => args[2] === 'Data为空'));
});
test('unrelated splash field diagnostics are retained', () => {
    const result = run({}, 'v4/client/getsplashscreen', 'GET');
    assert.ok(result.notifications.some(args => args[2] === 'List字段空'));
    assert.ok(result.notifications.some(args => args[2] === 'EnableGDT字段为空'));
});
test('header metadata matches the actual script execution log', () => {
    const version = code.match(/^ \* @version (.+)$/m)?.[1];
    const updated = code.match(/^ \* @updated (.+)$/m)?.[1];
    assert.match(version, /^\d{4}\.\d{2}\.\d{2}\.\d+$/);
    assert.match(updated, /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \+08:00$/);
    const result = run(base());
    assert.equal(result.logs[0][0], `[起点兼容修复] v${version} | 更新时间：${updated}`);
});

for (const [endpoint, input, field, expected] of [
    ['v4/client/getsplashscreen', {List: [{ad: 1}], EnableGDT: 1, Keep: 42}, 'List', null],
    ['v2/deeplink/geturl', {ActionUrl: 'QDReader://Bookstore', Keep: 42}, 'ActionUrl', ''],
    ['v1/adv/getadvlistbatch?positions=iOS_tab', {iOS_tab: [{ad: 1}], Keep: 42}, 'iOS_tab', []],
    ['v2/dailyrecommend/getdailyrecommend', {Items: [{ad: 1}], Keep: 42}, 'Items', []],
    ['v1/bookshelf/getHoverAdv', {ItemList: [{ad: 1}], Keep: 42}, 'ItemList', []],
]) {
    test(`existing endpoint preserved: ${endpoint}`, () => {
        const result = run(input, endpoint, 'GET');
        assert.deepEqual(result.body.Data[field], expected);
        assert.equal(result.body.Data.Keep, 42);
        assert.equal(result.notifications.length, 0);
        if (field === 'List') assert.equal(result.body.Data.EnableGDT, 0);
    });
}
