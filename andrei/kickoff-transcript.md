# Kick-off transcript — 21 Nov 2026, 10:44–11:00

Recorded in Granola by Andrei. **Automatic transcription:** no speaker labels, and names and terms are often misheard
(for example "Akbar" is Ahmad, Diligent's co-founder and CTO who presented Track 1; Edo/Eduardo presented Track 2;
both "Groq" and "Grok" appear; "Solomace"/"Tavoli" are probably sponsor names; "DocDragBot" is unclear).
The last two minutes (from 10:58) are our team talking after the talk.

## What matters for us (Andrei's reading)
- Scored on: correct verdicts against their true labels, explainable evidence, the same outcome across 5 runs,
  and a precise reason (the right verdict with the wrong reason is penalised).
- "A wrong decision is worse than no decision." (Ahmad, 10:52)
- Banks would take 90% accurate but 99.9% reproducible and explainable over 99.9% accurate but 90% reproducible. (Edo, 10:47)
- "It could be an agent, it could be rules, it doesn't matter." (Edo, 10:47)
- Track 1 data: 1,000 cases per institution archetype, partly real (anonymised), the rest generated from real patterns.
- Judges: Edo, Ahmad, Iskra, Natasha (in the room all day); guest speakers from Checkout and UBS. Solutions specific
  to financial crime are favoured.
- Choose one track only. The top 5 by score demo live, then 1st–3rd are chosen. Code freeze 17:00.
- Bring something visual for the demo.

## Transcript

**[10:44:25]** The insurance product that they offer you. And so once you're on board, they will monitor your activity. So ensure that you're not doing weird things with your money. If you're a teacher and you declare that you have a salary of X at onboarding in your maze in the UK, if you start sending tens of thousands of dollars every single day in the span of a few hours, in the span of a few weeks, to somebody in a high-risk country, let's say North Korea, the bank will stop the payment and will ask you, what are you doing? And so that's what we would call sort of a transaction monitor. And once that is done, if an investigation on transactions leads the team to believe that you're doing fraud or you're committing crime, then they will have to basically file a report with the crime agencies across the world that they work with.

**[10:45:09]** This is obviously a little bit oversimplified, the entire set of tasks that these teams have to run. And as you can imagine, if you're at large institutions, and we have some incredible judges that come from some of the best ones in the world that we'll introduce you later, You start to have millions and millions and millions of these tasks a day. Therefore, that's why you end up hiring hundreds of people, if not thousands. So that's a little bit at a high level. If you will have questions, we'll be moving around today to ensure that you get all the context you need. I'll just maybe present one of the tasks and then I'll get my CTO to explain the second one. I'll start actually with the second one, which is, is my customer actually being sanctioned? So you'll be able to see this task. Essentially, the problem is the following.

**[10:45:52]** Your board puts in 2 revenue today, they'll check your aim against these sanctions watches and dividers.

**[10:45:57]** So they'll take your John Doe name, send it to these providers. These providers essentially build up massive databases of criminal individuals, sanctioned individuals, people that committed bad actions.

**[10:46:09]** And in these databases, they have profiles with John Doe that did this bad action with this article 5 years ago.

**[10:46:15]** And through their search engine, they will bring back matches that an analyst needs to investigate to ensure it is not actually the customer that they're reporting. So John Doe is my customer, it's matched to a John Doe that murdered somebody in Kenya 6 years ago is that actually my customer or not? Fundamentally an entity resolution problem. So we've compiled a dataset that you'll be able to download here in which we have about a couple hundred matches of real customers. Real matches that came back from these providers. Some are sanctioned individuals, some have low enforcement issues, and some showed up in the news as bad actors, and some are also politically exposed persons. And the objective is for you to build a capability that enables an AI analyst to automatically decide whether the match is actually a true positive or, as it usually happens, a false positive. You will have pretty much the whole day, obviously, to work on it.

**[10:47:13]** The only thing that matters is not just how precisely are you able to decide whether an alert is a match or not and is a true positive or not, but also To what extent can you make that decision explainable, which is one of the most important things in this industry that sometimes prevents great technology from being adopted simply because it's effective but not explainable. So explainability is a big factor. And then the other one is Reproducibility. So maybe you build a model, it could be an agent, it could be rules, it doesn't matter. Feel free to explore here.

**[10:47:42]** But we want you to run the outcome of the, on the dataset 5 times and present back All the 5 outcomes that you received and try to ensure that the reproducibility is as close as possible to 100%. Because some of the largest banks in the world might take a model that is 90% accurate but 99.9% reproducible and explainable versus a 99.9% precise model that is only 90% explainable or reproducible. So that is something super important to keep in mind. You will get a lot of information within the data, more than I can frankly explain to you right now. So if you like this task, start working on it when we kick it off. If you have any questions, come to me or some of the amazing devs we have on the team, and I'll pass it on to my CTO. Thanks, guys.

**[10:48:37]** Hi guys, uh, good to have you here. Um, I'm Akbar, I'm the CTO of the fund. Um, I'm gonna tell you much about myself, but it's my job to do that, right?

**[10:48:48]** Yeah, is that better? Oh yeah. So I'm Ahmad, co-founder and CTO. I'm gonna walk you through the track 1. Which touches the second part of the task, which is the second part of the onboarding, uh, building on what Edo presented. So after your customer's onboarded, they will make payments, and these payments, some of them will be suspicious. And most of them will not be. So that's the other side of that. So just to kind of like come touch base where this transaction happens and how the monitoring happens.

**[10:49:30]** In general.

**[10:49:32]** A customer moves money in one way or another, then we have a set of rules that get triggered. These are industry-wide rules, are very common. They only differ by the type of institution. I'll explain them in a second.

**[10:49:48]** And after that, where there's an alert that's coming, it's being reviewed by an analyst.

**[10:49:53]** Which is a human analyst with expertise, and this person will decide if they will either close it, meaning that that's good, there's nothing to worry about.

**[10:50:01]** Or request for information, RFI, means to get back to the customer and ask them for maybe an ID, maybe a proof of the transfer, or whatever the transfer is related to. Escalate, it means they escalated to an accountable person, it's known as the MLRO, and that's the Money Laundering Reporting Officer, and they are deciding the trade-off of escalating further, stopping, etc.

**[10:50:29]** So this is where we stop. We don't go closer, like deeper in what the MLRO will do. So yeah, so these are the steps and where your system fits is where the analyst review the alert. So what you want to do is to build a system that is able to review the alert.

**[10:50:46]** And that system will have decision, one out of the 3, and we'll have a reason. So, and that's the kind of the outcome of that system. And the reason is the same as Eduardo mentioned, it has to be explainable just going a bit deeper here. So here's some examples of like real like bank statement or a transaction list for certain customers. I'll let you go through it here, just example to make it a bit easier for you. Let's go on what you're going to start with. So let me first start with the archetypes. So we created archetype customers.

**[10:51:19]** That exist in real life. And the archetypes customer is one is a bank, one is a payment and FX firm for businesses, meaning A payment service company that would convert dollar to euro or like convert money in general sent overseas, mostly for suppliers.

**[10:51:40]** E-money firm, that's a bit closer to what you get from an e-wallet. Could be something similar to like X Money, for example, from SpaceX. Like trading 212, maybe a lot of you guys know it, or any other type of investment. So these type of institutions have different way of operating, have different risk, therefore they have different archetype of what problems do we see. So for each, we will have 1,000 cases. These cases are partially real cases that is anonymized, and the rest is augmented based on similar patterns that happens in real life.

**[10:52:21]** So when you get those cases, what you need to build is a system that's able to decide that.

**[10:52:28]** Just kind of going closer to what you would need to create.

**[10:52:33]** This is all details you should go through. This is what is the most important part I want to cover, the way we will assess that it will be based on how correct The results are based on the true labels that we already know.

**[10:52:50]** And really important to add this, like a wrong decision is worse than no decision. So that's really important.

**[10:52:59]** Explainable evidence, so you need to really explain how you came up with this evidence or your system does that.

**[10:53:06]** And same as the other task, it needs to be reproducible, same outcome among 5 runs.

**[10:53:13]** And the last one is the reason itself has to be precise. So you can make the right verdict, but maybe it's the wrong reason. So, and this is more on how the scoring looks like for the task.

**[10:53:26]** So that's it. I mean, there's a lot of details. You should go through it. If you have any questions, just grab me, ask more questions, but just give it like good 10 minutes reading the page as a whole first and then ask me any questions you have in mind.

**[10:53:42]** Cool. Okay, so why take a deep dive into these 2 tracks? I think because financial crime Not only am I not an expert, but I think all of you need to— I mean, that right there deep dives into use cases and what Edo and yourself, Ahmed, care about. And the whole goal at the end of the day, they are judging as well. So they're your hearing it straight from the judges. Cool. Now the schedule, I think we're a bit, we're a bit, well, actually we're on time. Great.

**[10:54:16]** And then we'll start building. But I mean, good to touch on like and thank really more Eduardo and for making this like the collab. Then also like you'll have Solomace, you'll have Tavoli as well. You should be able to go to Discord, the channel, I think it's called like credits claim, and then you could go forward slash claim and then you should be able to claim your credits. You should have a walkthrough of how you can get your hands on Groq credits and get all your requests to start. You should be able to now, and I think people have already started, which is great. And then actually, like, just a shout out to the judges. We're doing a whole day, this one. Okay, so it's a whole day hack, right? So Code Freeze is at 5, right? Look at the people who are judging, right?

**[10:55:00]** Iscra, Natasha, who are at the front row, they took the day to actually come here. Maybe even grab them. I don't want to maybe have your whole day talking, but you know, it's a financial crime is like quite a like vertical specific industry, and I think that will come with like some vertical specific projects, ones that will kind of be more heavily Edo and Ahmed will care more about it as well, and also Iskra and also Natasha. And we'll have other lecturers that are coming as well who are, you know, in companies like Checkout and UBS even.

**[10:55:35]** Like Ahmed and Edo mentioned, this is kind of how we would be assessing the demos.

**[10:55:42]** You have access to all of this. Okay. And then the tech partners. So we have, like I said, Robot. You also, as a consequence, you'll get 1 month premium with these 30. Essentially, you'll have access to Cursor as well. And you, what I suggest you do is you should immediately go to the bot templates and get something called a DocDragBot. If you do not know who Lauren Tan is, do read. She's an absolute legend. I think when it comes to creating vertically specific or use case specific, AKA for hackathons, Probably the best setup is you start with DocDragBot. You basically talk about how you want to go about addressing these 2 tracks, either or. You have to choose one track, by the way. You can't do 2, right? So when you submit, we force you to choose one track, of course. And then, you know, what's at stake? We will have 5, the top 5 scored projects.

**[10:56:38]** Non-track specific, maybe the top 5 end up in one track. That could be a possibility, but we will have top 5 projects, top scoring.

**[10:56:48]** Present.

**[10:56:49]** And then of those top 5, we'll have a second round after the live demos to then decide the first, second, and third place. And what's at stake is Ultra plans, guys, per person. So you'll be walking away with a good amount of usage. If you win, if you win, and honestly, I think that's it. That's it for like, so it's about like 3 minutes before. If you have any questions, grab us.

**[10:57:15]** You know, Discord us, ask anything. We are here. I'm here at least as well to talk about how to use GrokBot, how you want to use GrokBot, anything Grok, because you also have access to the Grok API. So I'll stop selling. Basically, That's hack. Thank you for coming.

**[10:57:37]** Yeah, if any questions actually are right now, might as well. If anyone has any burning questions, I mean, if not, just ask it on Discord if you're shy.

**[10:57:48]** Yeah, thank you. By the way, for venue, not only this room but around and outside you have as well, okay? And also behind.

**[10:57:57]** I think some smart people already camped there, which is fair for a shot. I see you, you're like peeping over. But you also have the rooms to the side as well, which is like far more extended. So go for it. Have a good hack, guys.

**[10:58:13]** Have you gotten the credits? Yes.

**[10:59:27]** Okay guys, so which tracks are you guys most preferring? I, I like number 1, but okay, number 1, 1-1. Okay, let's go so they have a dataset that you download. Yeah, so did you guys, did you guys manage to get like access and everything, all the credits? You got claim already? Yeah, I already had an account, so I have to do the $50 instead of the premium. Yeah, same. Do you guys have Claude Code or Codex as well? I have Claude. Okay.

**[11:00:12]** So do you know if we need to like, um, We have to build like a dashboard, a presentation, anything like that, or it's just like the score? Like, I don't know, we can ask, but I think, yeah, yeah, I think we need to present something as well, so having something visual would help. Um, usually you do, yeah. And it says on there, but I've not seen the dataset, but I suspect it's huge. 21 megabytes. Maybe we can find some table in another room. I think so. Yeah, there's
