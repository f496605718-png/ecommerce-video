// 校验 types.json：JSON 有效性 + 每个类型 category_match 覆盖 14 品类
const fs = require('fs');
const path = 'C:/Users/Administrator/projects/服装电商AI视频/knowledge/types.json';
const raw = fs.readFileSync(path, 'utf8');
const data = JSON.parse(raw);
console.log('✅ JSON 有效，schema_version =', data.schema_version, '| types =', data.types.length);

// 14 品类关键词组（品类词 + 子品类词，用于覆盖判定）
const groups = {
  '服装': ['连衣裙','礼服','冬装','高端面料','通勤西装','衬衫','牛仔','休闲','运动服','童装','内衣','家居服','旗袍','汉服','国风单品','羽绒','潮流','机能服','度假款','大众款','设计款','美式','针织','卫衣'],
  '美妆': ['美妆','护肤','彩妆','口红','香水','香氛','粉底','胭脂','眼影','面膜','唇釉','精华','国风彩妆','复古彩妆','潮流彩妆'],
  '食品': ['食品','零食','饮料','茶叶','中式糕点','黄酒','咖啡','甜品','小吃','冲泡','老字号食品','传统糕点','分子料理','未来感食品','酒类','糕点'],
  '3C数码': ['3C','3C数码','数码','手机','电脑','耳机','音箱','键盘','相机','平板','充电','游戏外设','复古数码','胶片相机'],
  '家居': ['家居','家具','床品','灯具','窗帘','餐具','卫浴','收纳','装饰','地毯','沙发','家纺','软装','香薰','茶具','瓷器','新中式家具','中古家具','复古家居','智能家居','氛围灯具','生活用品'],
  '鞋靴': ['鞋靴','运动鞋','皮鞋','靴','凉鞋','帆布鞋','老爹鞋','高跟鞋','绣花鞋','布鞋','机能鞋','潮流鞋靴','复古鞋靴','跑鞋'],
  '箱包': ['箱包','手提包','双肩包','斜挎包','旅行箱','行李箱','钱包','手袋','皮具','中式箱包','机能箱包','复古箱包','油蜡皮包'],
  '配饰': ['配饰','帽子','围巾','腰带','眼镜','丝巾','手套','领带','中式配饰','复古配饰','机能配饰','金属配饰','格纹围巾','刺绣流苏'],
  '个护': ['个护','洗护','洗发水','沐浴露','牙膏','牙刷','剃须刀','香皂','草本洗护','中药洗护','复古洗护','电动牙刷'],
  '母婴': ['母婴','奶粉','纸尿裤','玩具','推车','奶瓶','辅食','孕妇','国风童装','周岁礼盒','智能母婴用品','母婴礼盒','安抚','复古童装','童装'],
  '运动户外': ['运动户外','健身','露营','骑行','帐篷','登山','瑜伽','球类','渔具','户外装备','健身器材','夜骑装备','运动机能装备','国潮联名装备','徒步装备','复古单车','经典运动装备','户外'],
  '宠物': ['宠物','猫粮','狗粮','猫砂','宠物玩具','宠物窝','牵引','宠物主粮','宠物粮','智能宠物用品','智能喂食器','国潮宠物用品','复古宠物用品'],
  '汽车用品': ['汽车用品','车膜','脚垫','车载','养护','座垫','行车记录','车品','安全座椅','智能车载','车载电子','车载香薰','新中式车品','复古车品','汽车'],
  '珠宝钟表': ['珠宝','钟表','项链','手镯','戒指','手表','腕表','翡翠','玉石','金饰','珍珠','钻石','首饰','机械手表','钛金饰品','复古珠宝','珍珠饰品']
};

let allPass = true;
console.log('\n=== 每个类型 category_match 覆盖检查 ===');
for (const t of data.types) {
  const cm = t.category_match.join(' ');
  const missing = [];
  for (const [cat, toks] of Object.entries(groups)) {
    const hit = toks.some(tok => cm.includes(tok));
    if (!hit) missing.push(cat);
  }
  const hasMaterial = Array.isArray(t.material_match);
  const status = missing.length === 0 ? '✅ 14/14' : `❌ 缺 ${missing.length}: ${missing.join('/')}`;
  if (missing.length > 0) allPass = false;
  console.log(`${t.icon} ${t.name.padEnd(10)} ${status}  | category_match=${cm.split(' ').length}词 | material_match=${hasMaterial ? '✅(' + t.material_match.join(',') + ')' : '❌缺失'}`);
}

console.log('\n=== 14 品类整体覆盖（全类型并集）===');
for (const [cat, toks] of Object.entries(groups)) {
  const allWords = data.types.flatMap(t => t.category_match).join(' ');
  const hitCount = data.types.filter(t => t.category_match.some(w => toks.some(tok => w.includes(tok)))).length;
  console.log(`${cat}: 命中类型数 = ${hitCount}${hitCount >= 2 ? ' ✅' : ' ⚠️'}`);
}
console.log(allPass ? '\n✅ 全部 12 类型均覆盖 14 品类' : '\n⚠️ 存在未覆盖项');
